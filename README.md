# Build package

Compile:
```bash
python setup.py sdist
```

Upload package to PyPi.org
```bash
twine upload --repository pypi dist/django-solr-dsl-0.6.tar.gz --config-file .pypirc
```

