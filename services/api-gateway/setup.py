from setuptools import setup, find_packages

setup(
    name="api_gateway",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "quart",
        "celery",
        "redis",
        "sqlalchemy",
        "hypercorn"
    ],
) 