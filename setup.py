#!/usr/bin/env python

from distutils.core import setup

setup(
    name='ikwi',
    version='0.1',
    description='A personal wikiware.',
    author='David P. Kendal',
    author_email='pypi@dpk.io',
    url='https://github.com/dpk/ikwi',
    packages=['ikwi'],
    package_dir={'ikwi': '.'},
    scripts=['ikwi'],
    requires=[
        'bcrypt>=1.1.1',
        'html5lib==0.999',
        'Jinja2>=2.7.3',
        'lxml>=3.4.3',
        'pypandoc==0.9.7',
        'PyYAML==3.11',
        'Werkzeug>=0.10.4',
        'whoosh>=2.7.0'
    ]
)
