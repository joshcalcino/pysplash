import os.path
import tempfile

# from pathlib import Path

from ctypes import (c_int, c_float, c_bool, c_double, c_char_p,
                        byref, POINTER, pointer, cast, c_char)

from . import _libread as libread
from ..utils import stdchannel_redirected
import numpy as np
import h5py
from pandas import DataFrame
import time

# Global constants that specify the length of strings in some of the
# SPLASH subroutines. Changing these could break the code and lead to a
# Segmentation Fault
ltags = 16
lenlabel = 80
lenunitslabel = 40


class Dump:
    """PySPLASH Dump object. Contains SPH data, labels, units, and other
    attributes.


    """

    def __init__(self, data=None, labels=None, headers=None, filepath=None, filetype=None):
        self.data = data
        self.labels = labels
        self.headers = headers
        self.filepath = filepath
        self.filetype = filetype

        self._as_dataframe = None
        self._as_hdf5 = None

    def __getitem__(self, name):
        if name in ['headers', 'header']:
            return self.headers

        if name in self.labels:
            try:
                col = self.labels.index(name)
            except ValueError:
                print("Label {} not a column name in dumpfile".format(name))
                raise

            return self.data[col]

        if self.as_dataframe is not None:
            return self.as_dataframe[name].values
        else:
            self._to_dataframe()
            return self.as_dataframe[name].values

    @property
    def as_dataframe(self):
        if self._as_dataframe is None:
            self._as_dataframe = DataFrame(data=self.data, columns=self.labels)
        return self._as_dataframe

    @property
    def as_hdf5(self):
        if self._as_hdf5 is None:
            self._as_hdf5 = self._to_hdf5_dataset()
        return self._as_hdf5

    def _to_hdf5_dataset(self):
        fname = os.path.basename(self.filepath) + b'.h5'
        tf = tempfile.NamedTemporaryFile()
        f = h5py.File(tf, 'w')
        f = _dump2hdf5(f, self)
        return f

    def save_hdf5(self, filename):
        if self.filetype is 'phantom':
            print("Warning: save_hdf5 cannot be used to rerun phantom simulations. ")

        dump_hdf5 = self.as_hdf5

        with h5py.File(filename, "w") as f:
            for group_name in dump_hdf5:
                f_a = f.create_group(group_name)
                for dataset in dump_hdf5[group_name]:
                    f_a.create_dataset(dataset, data=dump_hdf5[group_name][dataset])


def _dump2hdf5(f, dump):
    """ Convert the attributes of the Dump class into an HDF5 File object. """

    if dump.headers is not None:
        f_header = f.create_group('header')
        for header in dump.headers:
            f_header.create_dataset(header, data=dump.headers[header])

    if dump.filetype.lower().decode() == 'phantom':
        return _phantom2hdf5(f, dump)

    f_particles = f.create_group('particles')

    _store_remainder(f_particles, dump)

    return f


def _phantom2hdf5(f, dump):
    """ A simple tool for converting to HDF5 format for use in other codes (e.g. Plonk)

    NOTE: This is not a replacement for phantom2hdf5, and not all of the contents
          are stored in these files. They do not contain enough information to
          restart a Phantom simulation.
    """

    _store_extra_header_quantities(f['header'], dump)

    # Mask out the sink particles so we can store them in a different Group
    sink_mask = dump['itype'] == 3
    sink_indices = np.where(sink_mask)

    ignore_labels = []

    if len(sink_indices) > 0:
        f_sinks = f_particles = f.create_group('sinks')

        # Ignore x, y, z, since they are added into the xyz group
        ignore_labels.extend(['x', 'y', 'z'])

        sink_xyz_data = np.array([dump['x'][sink_indices], dump['y'][sink_indices], dump['z'][sink_indices]]).T
        f_sinks.create_dataset('xyz', data=sink_xyz_data)

        if 'vx' in dump.labels:
            # If velocity is present, it is a full dump
            _store_fulldump(f_sinks, dump, mask=sink_mask, ignore_labels=ignore_labels)

        _store_remainder(f_sinks, dump, mask=sink_mask, ignore_labels=ignore_labels)


    # Find particles based off our sink mask made earlier
    particle_mask = np.logical_not(sink_mask)
    particle_indices = np.where(particle_mask)

    f_particles = f.create_group('particles')

    # Ignore x, y, z, since they are added into the xyz group
    ignore_labels.extend(['x', 'y', 'z'])

    particle_xyz_data = np.array([dump['x'][particle_indices], dump['y'][particle_indices], dump['z'][particle_indices]]).T
    f_particles.create_dataset('xyz', data=particle_xyz_data)

    if 'vx' in dump.labels:
        _store_fulldump(f_particles, dump, mask=particle_mask, ignore_labels=ignore_labels)

    _store_remainder(f_particles, dump, mask=particle_mask, ignore_labels=ignore_labels)

    return f


def _store_fulldump(f_a, dump, mask=None, ignore_labels=[]):
    """ Store velocity components of a fulldump """
    f_a.create_dataset('vxyz', data=np.array([dump['vx'][mask], dump['vy'][mask], dump['vz'][mask]]))
    f_a.create_dataset('divv', data=dump['divv'][mask])
    # f_a.create_dataset('dt', data=dump['dt'][mask])

    if len(ignore_labels) > 0:
        # Ignore these quantites since they are added into groups
        ignore_labels.extend(['vx', 'vy', 'vz', 'divv']) # , 'dt'])


def _store_remainder(f_a, dump, mask=None, ignore_labels=[]):
    """ Store additional labels from dump if they are not already in the HDF5 file object """
    for label in dump.labels:
        if label not in (f_a.keys() and ignore_labels):
            f_a.create_dataset(label, data=np.array(dump[label][mask]))


def _store_extra_header_quantities(f_a, dump):
    """ Store some extra quantities that Plonk needs. """
    if 'ieos' not in f_a.keys():
        f_a.create_dataset('ieos', data=3)

    if 'massoftype' not in f_a.keys():
        massoftype = []
        for key in f_a.keys():
            if 'massoftype' in key:
                massoftype.append(f_a[key][()])

        f_a.create_dataset('massoftype', data=np.array(massoftype))


def read_data(filepath, filetype='Phantom', use_HDF5=False,
                     ncol=None, npart=None, verbose=False):
    """Generate a Snap object from a Phantom HDF5 file.
    Parameters
    ----------
    filepath
        The path to the file.
    filetype
        The format of the file. Will load HDF5 files if specified,
        otherwise a binary data format supported by SPLASH can be read
    use_HDF5
        Boolean to specify whether to use the HDF5 library to read files.
    ncol, npart
        The number of columns and particles in the data. Incorrectly
        specifying these can lead to a Segmentation Fault
    verbose
        Specify if you want libread to provide output to the terminal

    Returns
    -------
    Dump
        A Dump object.
    """

    if not os.path.exists(filepath):
        raise FileNotFoundError("filepath " + str(filepath) + " does not exist.")

    extension = os.path.splitext(filepath)

    if use_HDF5 is True:
        #any(ext in ['h5', 'hdf5'] for ext in [filetype.lower(), extension]) or \
        #                    use_HDF5 is True:
        return read_hdf5(filepath)

    else:
        return read_data_binary(filepath, filetype=filetype,
                             ncol=None, npart=None, verbose=False)


def read_hdf5(filepath):
    if not h5py.is_hdf5(filepath):
        raise TypeError("File given is not an HDF5 file.")

    return h5py.File(filepath, mode='r')


def read_data_binary(filepath, filetype='Phantom',
                     ncol=None, npart=None, verbose=False):

    filepath = filepath.encode('utf-8')
    filetype = filetype.encode('utf-8')

    f_length = c_int(len(filepath))
    ff_length = c_int(len(filetype))

    # set up verbosity
    if verbose:
        verbose_int = c_int(1)
        print_warnings = True
    else:
        print_warnings = False
        verbose_int = c_int(0)

    # We need to know the amount of memory to allocate. If this is not yet
    # given, we need to find out how much to allocate.
    if ncol is None or npart is None:
        # ncol and npart will be obtained from our first call to libread.read_data
        # This first call will not result in the data actually being loaded
        # for some data formats, e.g.
        # Phantom, SPHng, gadget, and others,

        ncol_in = 0
        npart_in = 0

        ncol_in_c = c_int(ncol_in)
        npart_in_c = c_int(npart_in)

        # Fortran read_data subroutine arguments are:
        # filename,fileformat,f_length, ff_length,&
        # sph_dat,npart,ncol,read_header,verbose,ierr

        # Tell ctypes what data types we are going to send to our Fortran code
        libread.read_data.argtypes = \
                [c_char_p, c_char_p, POINTER(c_int), POINTER(c_int),
                 POINTER(c_double * npart_in * ncol_in), POINTER(c_int), POINTER(c_int),
                 POINTER(c_int), POINTER(c_int), POINTER(c_int)]

        sph_dat = (c_double * npart_in * ncol_in)() # Order of npart and ncol matters here

        # Capture error flag with an integer
        ierr = c_int(0)

        # Indicate that we just want to read the header to get ncol and npart
        read_header = c_int(1)

        with stdchannel_redirected():
            libread.read_data(c_char_p(filepath), c_char_p(filetype),
                              byref(f_length), byref(ff_length),
                              byref(sph_dat),
                              byref(npart_in_c), byref(ncol_in_c),
                              byref(read_header), byref(verbose_int), byref(ierr))


        if verbose: print("Got file size, ncol="+ str(ncol_in_c) +
                            ", npart=" + str(npart_in_c))

        ncol = ncol_in_c
        npart = npart_in_c

    else:
        # If ncol and npart are given, convert to c_int
        npart = c_int(npart)
        ncol = c_int(ncol)

    # Update argtypes based on array size
    libread.read_data.argtypes = \
            [c_char_p, c_char_p, POINTER(c_int), POINTER(c_int),
             POINTER(c_double * npart.value * ncol.value), POINTER(c_int), POINTER(c_int),
             POINTER(c_int), POINTER(c_int), POINTER(c_int)]

    sph_dat = (c_double * npart.value * ncol.value)()

    ierr = c_int(0)
    read_header = c_int(0)

    with stdchannel_redirected(print_warnings=print_warnings):
        libread.read_data(c_char_p(filepath), c_char_p(filetype), # strings
                              byref(f_length), byref(ff_length), # length of previous strings
                              byref(sph_dat), # An array with the size of the SPH data
                              byref(npart), byref(ncol), # the size of sph_dat
                              byref(read_header), byref(verbose_int), byref(ierr))

    if ierr == 1:
        raise RuntimeError("Error encountered in SPLASH.")

    # Turn data into a numpy array
    sph_data = np.ctypeslib.as_array(sph_dat) # .T

    labels = get_labels(ncol.value-1) # subtract 1 since itype is not included

    labels.append('itype') # Last column is always particle type
    header_tags, header_vals = get_headers()

    dump = Dump(data=sph_data, labels=labels,
                headers=dict(zip(header_tags, header_vals)),
                filepath=filepath, filetype=filetype)

    return dump


def get_labels(ncol):
    if type(ncol) is c_int:
        ncol_py = ncol.value

    elif type(ncol) is int:
        ncol_py = ncol
        ncol = c_int(ncol)

    number_chars = lenlabel * ncol_py

    # Some Fortran compilers do not like passing an array of c_char[n]
    labels = (c_char * lenlabel * ncol_py)()

    libread.get_labels_c.argtypes = [POINTER(c_char * lenlabel * ncol_py), POINTER(c_int)]

    libread.get_labels_c(byref(labels), byref(ncol))

    labels = [str(labels[i].value.rstrip(), 'utf-8') for i in range(0, ncol.value)]

    return labels


def get_headers():

    headerval_length = c_int()
    headertag_length = c_int()

    libread.get_header_vals_size.argtypes = [POINTER(c_int), POINTER(c_int)]

    libread.get_header_vals_size(byref(headertag_length), byref(headerval_length))

    headertags = (c_char * ltags * headertag_length.value)()
    headervals = (c_double * headerval_length.value)()

    libread.get_headers.argtypes = [POINTER(c_char * ltags * headertag_length.value),
                                    POINTER(c_double * headerval_length.value),
                                    POINTER(c_int), POINTER(c_int)]

    libread.get_headers(byref(headertags), byref(headervals),
                        byref(headertag_length), byref(headerval_length))



    headertags = [str(headertags[i].value.rstrip(), 'utf-8')
                    for i in range(0, headertag_length.value)]


    headervals = np.ctypeslib.as_array(headervals)

    headertags_clean = list()
    headervals_clean = list()

    for i, headertag in enumerate(headertags):
        if headertag != '':
            headertags_clean.append(headertag)
            headervals_clean.append(headervals[i])

    return headertags_clean, headervals_clean
