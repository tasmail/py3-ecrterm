from setuptools import find_packages, setup

from ecrterm import __version__

setup(
    name='py3-ecrterm',
    version=__version__,
    packages=find_packages(exclude=['ecrterm.tests']),
    license='LGPL-3',
    install_requires=['pyserial', 'six'],
    extras_require={'cli': ['prompt_toolkit>=3', 'rich>=12']},
    entry_points={'console_scripts': ['zvt=ecrterm.cli.main:run']},
    include_package_data=True,
    classifiers=[
        'License :: OSI Approved :: GNU Lesser General Public License v3 or '
        'later (LGPLv3+)',
    ],
)
