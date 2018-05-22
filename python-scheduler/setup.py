import os
from setuptools import setup


def read(fname):
    with open(os.path.join(os.path.dirname(__file__), fname)) as f:
        return f.read().strip()


setup(
    name='pbrt-scheduler',
    version='0.0.1',
    author='JZ',
    # url='http://github.com/StanfordVL/Surreal',
    description='Scheduler for multi-node pbrt',
    long_description=read('README.md'),
    keywords=['Ray tracing',
              'Computer graphics',
              'Distributed Computing'],
    # license='MIT',
    packages=['pbrt_scheduler'],
    entry_points={
        'console_scripts': [
            'pbrt-master=pbrt_scheduler.master:main',
            'pbrt-slave=pbrt_scheduler.slave:main',
            'pbrt-cluster=pbrt_scheduler.launch_cluster:main',
            'pbrt-client=pbrt_scheduler.client:main'
        ]
    },
    install_requires=[
        "pyzmq",
        "nanolog",
        "benedict",
    ],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Environment :: Console",
        "Programming Language :: Python :: 3"
    ],
    include_package_data=True,
    zip_safe=False
)
