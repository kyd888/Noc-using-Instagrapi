#!/bin/bash

# Replace the deprecated import in Flask helpers.py
sed -i 's/from werkzeug.urls import url_quote/from werkzeug.urls import url_quote_plus as url_quote/' /opt/render/project/src/.venv/lib/python3.11/site-packages/flask/helpers.py
