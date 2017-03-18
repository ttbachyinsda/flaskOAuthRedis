import gzip
import zipfile
import os
import functools
import tarfile
import sys
import shutil
import hashlib
import time
import redis
import json
from six.moves.urllib.request import urlopen
from six.moves.urllib.error import URLError
from six.moves.urllib.error import HTTPError
from six.moves.urllib.request import urlretrieve
import numpy as np


class Progbar(object):
    """Displays a progress bar.

    # Arguments
        target: Total number of steps expected.
        interval: Minimum visual progress update interval (in seconds).
    """

    def __init__(self, target, width=30, verbose=1, interval=0.05):
        self.width = width
        self.target = target
        self.sum_values = {}
        self.unique_values = []
        self.start = time.time()
        self.last_update = 0
        self.interval = interval
        self.total_width = 0
        self.seen_so_far = 0
        self.verbose = verbose

    def update(self, current, values=None, force=False):
        """Updates the progress bar.

        # Arguments
            current: Index of current step.
            values: List of tuples (name, value_for_last_step).
                The progress bar will display averages for these values.
            force: Whether to force visual progress update.
        """
        values = values or []
        for k, v in values:
            if k not in self.sum_values:
                self.sum_values[k] = [v * (current - self.seen_so_far),
                                      current - self.seen_so_far]
                self.unique_values.append(k)
            else:
                self.sum_values[k][0] += v * (current - self.seen_so_far)
                self.sum_values[k][1] += (current - self.seen_so_far)
        self.seen_so_far = current

        now = time.time()
        if self.verbose == 1:
            if not force and (now - self.last_update) < self.interval:
                return

            prev_total_width = self.total_width
            sys.stdout.write('\b' * prev_total_width)
            sys.stdout.write('\r')

            numdigits = int(np.floor(np.log10(self.target))) + 1
            barstr = '%%%dd/%%%dd [' % (numdigits, numdigits)
            bar = barstr % (current, self.target)
            prog = float(current) / self.target
            prog_width = int(self.width * prog)
            if prog_width > 0:
                bar += ('=' * (prog_width - 1))
                if current < self.target:
                    bar += '>'
                else:
                    bar += '='
            bar += ('.' * (self.width - prog_width))
            bar += ']'
            sys.stdout.write(bar)
            self.total_width = len(bar)

            if current:
                time_per_unit = (now - self.start) / current
            else:
                time_per_unit = 0
            eta = time_per_unit * (self.target - current)
            info = ''
            if current < self.target:
                info += ' - ETA: %ds' % eta
            else:
                info += ' - %ds' % (now - self.start)
            for k in self.unique_values:
                info += ' - %s:' % k
                if isinstance(self.sum_values[k], list):
                    avg = self.sum_values[k][0] / max(1, self.sum_values[k][1])
                    if abs(avg) > 1e-3:
                        info += ' %.4f' % avg
                    else:
                        info += ' %.4e' % avg
                else:
                    info += ' %s' % self.sum_values[k]

            self.total_width += len(info)
            if prev_total_width > self.total_width:
                info += ((prev_total_width - self.total_width) * ' ')

            sys.stdout.write(info)
            sys.stdout.flush()

            if current >= self.target:
                sys.stdout.write('\n')

        if self.verbose == 2:
            if current >= self.target:
                info = '%ds' % (now - self.start)
                for k in self.unique_values:
                    info += ' - %s:' % k
                    avg = self.sum_values[k][0] / max(1, self.sum_values[k][1])
                    if avg > 1e-3:
                        info += ' %.4f' % avg
                    else:
                        info += ' %.4e' % avg
                sys.stdout.write(info + "\n")

        self.last_update = now

    def add(self, n, values=None):
        self.update(self.seen_so_far + n, values)


def validate_file(fpath, md5_hash):
    """Validates a file against a MD5 hash.

    # Arguments
        fpath: path to the file being validated
        md5_hash: the MD5 hash being validated against

    # Returns
        Whether the file is valid
    """
    hasher = hashlib.md5()
    with open(fpath, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    if str(hasher.hexdigest()) == str(md5_hash):
        return True
    else:
        return False


def get_file(fname, origin, untar=False,
             md5_hash=None, cache_subdir='datasets'):
    """Downloads a file from a URL if it not already in the cache.

    Passing the MD5 hash will verify the file after download
    as well as if it is already present in the cache.

    # Arguments
        fname: name of the file
        origin: original URL of the file
        untar: boolean, whether the file should be decompressed
        md5_hash: MD5 hash of the file for verification
        cache_subdir: directory being used as the cache

    # Returns
        Path to the downloaded file
    """
    datadir_base = os.path.expanduser(os.path.join('~', '.ttbweb'))
    if not os.access(datadir_base, os.W_OK):
        datadir_base = os.path.join('/tmp', '.ttbweb')
    datadir = os.path.join(datadir_base, cache_subdir)
    if not os.path.exists(datadir):
        os.makedirs(datadir)

    if untar:
        untar_fpath = os.path.join(datadir, fname)
        fpath = untar_fpath + '.tar.gz'
        print(fpath)
    else:
        fpath = os.path.join(datadir, fname)
        print(fpath)

    download = False
    if os.path.exists(fpath):
        # File found; verify integrity if a hash was provided.
        if md5_hash is not None:
            if not validate_file(fpath, md5_hash):
                print('A local file was found, but it seems to be '
                      'incomplete or outdated.')
                download = True
    else:
        download = True

    if download:
        print('Downloading data from', origin)
        progbar = None

        def dl_progress(count, block_size, total_size, progbar=None):
            if progbar is None:
                progbar = Progbar(total_size)
            else:
                progbar.update(count * block_size)

        error_msg = 'URL fetch failure on {}: {} -- {}'
        try:
            try:
                urlretrieve(origin, fpath,
                            functools.partial(dl_progress, progbar=progbar))
            except URLError as e:
                raise Exception(error_msg.format(origin, e.errno, e.reason))
            except HTTPError as e:
                raise Exception(error_msg.format(origin, e.code, e.msg))
        except (Exception, KeyboardInterrupt) as e:
            if os.path.exists(fpath):
                os.remove(fpath)
            raise
        progbar = None

    if untar:
        if not os.path.exists(untar_fpath):
            print('Untaring file...')
            tfile = tarfile.open(fpath, 'r:gz')
            try:
                tfile.extractall(path=datadir)
            except (Exception, KeyboardInterrupt) as e:
                if os.path.exists(untar_fpath):
                    if os.path.isfile(untar_fpath):
                        os.remove(untar_fpath)
                    else:
                        shutil.rmtree(untar_fpath)
                raise
            tfile.close()
        return untar_fpath

    return fpath


def unzip_file(zipfilename):
    datasetname = ''
    zfobj = zipfile.ZipFile(zipfilename)
    datadir_base = os.path.expanduser(os.path.join('~', '.ttbweb'))
    if not os.access(datadir_base, os.W_OK):
        datadir_base = os.path.join('/tmp', '.ttbweb')
    datadir_base = os.path.join(datadir_base, 'datasets')
    for name in zfobj.namelist():
        name = name.replace('\\','/')
        nowname = os.path.join(datadir_base, name)
        if nowname.endswith('/'):
            os.mkdir(nowname)
        else:
            datasetname = nowname
            outfile = open(nowname, 'wb')
            outfile.write(zfobj.read(name))
            outfile.close()
    return datasetname


def load_coauthor_data():
    """Loads the dataset.
    # Arguments
        path: path where to cache the dataset locally
            (relative to ~/.ttbweb/datasets).

    # Returns
        Tuple of Numpy arrays: `(x_train, y_train), (x_test, y_test)`.
    """
    path = 'AMiner-Coauthor.zip'
    filepath = get_file(path, origin='http://arnetminer.org/lab-datasets/aminerdataset/AMiner-Coauthor.zip')
    return unzip_file(filepath)


def load_author_data():
    """Loads the dataset.
    # Arguments
        path: path where to cache the dataset locally
            (relative to ~/.ttbweb/datasets).

    # Returns
        Tuple of Numpy arrays: `(x_train, y_train), (x_test, y_test)`.
    """
    path = 'AMiner-Author.zip'
    filepath = get_file(path, origin='http://arnetminer.org/lab-datasets/aminerdataset/AMiner-Author.zip')
    return unzip_file(filepath)


pool = redis.ConnectionPool(host='127.0.0.1', port=6379)


def deal_coauthor_data():
    filepath = load_coauthor_data()
    file = open(filepath, 'r')
    lines = file.readlines()
    dict = {}
    i = 0
    for line in lines:
        i += 1
        if (i % 1000 == 0):
            print('deal line ', i, ' of ',len(lines))
        line = line[1:]
        line = line.replace('\t', ' ')
        author1 = int(line.split(' ')[0])
        author2 = int(line.split(' ')[1])
        cotime = int(line.split(' ')[2])
        if (author1 in dict.keys()):
            dict[author1][author2] = cotime
        else:
            dict[author1] = json.loads('{}')
            dict[author1][author2] = cotime
        if (author2 in dict.keys()):
            dict[author2][author1] = cotime
        else:
            dict[author2] = json.loads('{}')
            dict[author2][author1] = cotime
    r = redis.Redis(connection_pool=pool)

    num = 0
    for author in dict.keys():
        num += 1
        if (num % 1000 == 0):
            print('deal coauthor ', author, num, ' of ', len(dict))
        r.set('##coauthorof##'+str(author), json.dumps(dict[author]))


def remove_first_segment(string):
    c = string.find(' ')
    return string[c+1:]


def deal_author_data():
    filepath = load_author_data()
    file = open(filepath, 'r')
    lines = file.readlines()
    dict = {}
    reallines = []
    for linenum in range(0, len(lines)):
        line = lines[linenum]
        if (linenum < len(lines) - 1):
            k = 1
            while (linenum+k < len(lines) and lines[linenum+k] != '\n' and lines[linenum+k][0] != '#'):
                line += lines[linenum+k]
                k += 1
        if (line[0] == '#'):
            reallines.append(line)

    r = redis.Redis(connection_pool=pool)

    linenum = 0
    while (linenum < len(reallines)):
        index = int(remove_first_segment(reallines[linenum]))
        if (index % 1000 == 0):
            print('deal author ', index, ' of ',len(reallines)/9)
        name = remove_first_segment(reallines[linenum+1])
        name = name.replace('\n','')
        af = remove_first_segment(reallines[linenum+2])
        af = af.replace('\n','')
        pc = int(remove_first_segment(reallines[linenum+3]))
        cn = int(remove_first_segment(reallines[linenum+4]))
        hi = int(remove_first_segment(reallines[linenum+5]))
        pi = float(remove_first_segment(reallines[linenum+6]))
        upi = float(remove_first_segment(reallines[linenum+7]))
        t = remove_first_segment(reallines[linenum+8])
        t = t.replace('\n','')
        authordata = json.loads('{}')
        authordata['index'] = index
        authordata['name'] = name
        authordata['af'] = af
        authordata['pc'] = pc
        authordata['cn'] = cn
        authordata['hi'] = hi
        authordata['pi'] = pi
        authordata['upi'] = upi
        authordata['t'] = t
        subjects = t.split(';')
        for subject in subjects:
            if subject in dict.keys():
                dict[subject][index] = hi
            else:
                dict[subject] = json.loads('{}')
                dict[subject][index] = hi
        r.set('##authordataof##' + str(index), json.dumps(authordata))
        linenum += 9

    num = 0
    for subject in dict.keys():
        num += 1
        if (num % 1000 == 0):
            print('deal subject ', subject, num, ' of ', len(dict))
        r.set('##subject##' + subject, json.dumps(dict[subject]))

    file2 = open('subject.txt','w')
    for subject in dict.keys():
        file2.write(subject)
        file2.write('\n')
    file2.close()

def test_redis():
    r = redis.Redis(connection_pool=pool)
    print(r.get('##coauthorof##481437'))
    print(r.get('##authordataof##1'))
    print(r.get('##subject##environmental choice'))
    s = str(r.get('##subject##data mining'))
    s = s[2:-1]
    list = json.loads(s)
    for element in list.keys():
        print(element, list[element])


deal_coauthor_data()
deal_author_data()
test_redis()
