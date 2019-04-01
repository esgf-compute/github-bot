from setuptools import setup

setup(
    name='nimbus-bot',
    description='GitHub bot to process access requests to Nimbus cluster',
    packages=['nimbus_bot'],
    author='Jason Boutte',
    author_email='boutte3@llnl.gov',
    version='1.0.0',
    url='https://github.com/esgf-nimbus/nimbus-bot',
    entry_points={
        'console_scripts': [
            'nimbus-github-bot=nimbus_bot:main',
        ]
    },
)
