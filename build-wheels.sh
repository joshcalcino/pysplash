#!/bin/bash -e

# If MANLINUX is not set, assume no
if [ -z "$MANYLINUX" ]; then
  MANYLINUX=no
fi

#-- Make sure variables are not used uninitialised
set -u

# Use manylinux pythons if MANYLINUX=yes
# otherwise use default system python
if [ "${MANYLINUX}" == "yes" ]; then
  PYTHONS=/opt/python/cp3*/bin/python
else
  PYTHONS=python
fi

OS=$(uname -s)

# Choose between delocate and auditwheel, and set the directory
# (within the package) to copy the external libraries to.
# Also, hardcode the platform tag for MacOS, otherwise deallocate won't work.
# Note that auditwheel will automatically change the platform tag.
if [ "${OS}" == "Darwin" ]; then
  DELOCATE_TOOL='delocate-wheel -v'
  LIB_DIR=libs/.dylibs
  PLAT=macosx_10_9_x86_64
  PLAT_FLAG="--plat-name ${PLAT}"
else
  DELOCATE_TOOL='auditwheel repair'
  LIB_DIR=/libs/
  PLAT_FLAG=
fi

# Set directories for bad and good wheels
BAD_WHEELS=.tmpwheelhouse
WHEELHOUSE=wheelhouse

# Clean out any old wheels in the bad wheels folder (if present)
rm ${BAD_WHEELS}/*.whl || true

# Compile wheels
for PYTHON in $PYTHONS; do
  # Clean build dir
  ${PYTHON} setup.py clean --all
  rm src/libs/*.so || true
  # Create wheel
  ${PYTHON} setup.py bdist_wheel ${PLAT_FLAG} --dist-dir ${BAD_WHEELS}
done

# Delocate wheels (remove external lib dependencies by including relevant libs in wheel)
# Note: these tools also relink libraries for you by modifying their ELFs
for whl in ${BAD_WHEELS}/*.whl; do
  ${DELOCATE_TOOL} -L ${LIB_DIR} -w ${WHEELHOUSE} ${whl}
done

# Delete the bad wheels folder
rm -rf ${BAD_WHEELS} || true
