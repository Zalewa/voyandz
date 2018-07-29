# coding: utf-8
from setuptools import setup

with open('LICENSE') as f:
    license = f.read()

with open('README.md') as f:
    readme = f.read()

version = {}
with open('voyandz/version.py', 'r') as f:
    exec(f.read(), version)

setup(
    name='voyandz',
    version=version['VERSION'],
    description='Voyoffnik Andzej - an AV HTTP piping server',
    long_description=readme,
    author='Robikz',
    author_email='zalewapl@gmail.com',
    license=license,
    include_package_data=True,
    packages=['voyandz'],
    install_requires=[
        'Flask',
        'PyYAML'
    ],
    entry_points={
        'console_scripts': ['voyandz=voyandz.cli:main']
    }
)
