#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import glob


from setuptools import setup
from setuptools.extension import Extension

try:
    from Cython.Distutils import build_ext as _build_ext
    from Cython.Build import cythonize

    HAVE_CYTHON = True
except ImportError:
    from setuptools.command.build_ext import build_ext as _build_ext

    HAVE_CYTHON = False


def get_ext_modules():
    ext = ".pyx" if HAVE_CYTHON else ".c"
    src_files = glob.glob(
        os.path.join(os.path.dirname(__file__), "pairtools", "lib", "*" + ext)
    )
    ext_modules = []
    for src_file in src_files:
        name = "pairtools.lib." + os.path.splitext(os.path.basename(src_file))[0]
        if not "pysam" in name and not "regions" in name:
            ext_modules.append(Extension(name, [src_file]))
        elif "regions" in name:
            ext_modules.append(
                Extension(
                    name,
                    [src_file],
                    language="c++",
                )
            )
        else:
            import pysam
            ext_modules.append(
                Extension(
                    name,
                    [src_file],
                    extra_link_args=pysam.get_libraries(),
                    include_dirs=pysam.get_include(),
                    define_macros=pysam.get_defines(),
                    #extra_objects=pysam.get_libraries(),
                )
            )

    if HAVE_CYTHON:
        # .pyx to .c
        ext_modules = cythonize(ext_modules)  # , annotate=True

    return ext_modules


class build_ext(_build_ext):
    # Extension module build configuration
    def finalize_options(self):
        _build_ext.finalize_options(self)
        import numpy
        self.include_dirs.append(numpy.get_include())

    def run(self):
        # Import numpy here, only when headers are needed
        import numpy

        # Add numpy headers to include_dirs
        self.include_dirs.append(numpy.get_include())

        # Call original build_ext command
        _build_ext.run(self)


setup(
    ext_modules=get_ext_modules(),
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    entry_points={
        "console_scripts": [
            "pairtools = pairtools.cli:cli",
            #'pairsamtools = pairtools.cli:cli',
        ]
    },
)
