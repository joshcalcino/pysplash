"""
PySplashSPH
=====
**PySplashSPH** is a Python package that provides access to the Fortran
subroutines from the SPH visualisation code SPLASH.
Features
--------
- Plotting exact analytic functions for many hydrodynamical problems
- Reading many SPH code data formats
- Interpolation routines for SPH visualisation
Subpackages
-----------
- exact
    Contains functions for exact solutions to many hydrodynamical
    problems
- read
    Contains functions for reading data formats from many different
    SPH codes
- interpolation
    Contains functions for SPH interpolation
Documentation
-------------
See **** for documentation. The source code is
available at ****.
"""

__version__ = '0.0.2-1'

from . import exact, read, utils #, interpolation

__all__ = (['exact', 'read', 'utils'])
