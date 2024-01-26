#!/bin/sh -l

echo "$PWD"
flake8 --ignore=I001,I005,E501,W503
