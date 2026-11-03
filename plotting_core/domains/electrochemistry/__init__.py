"""Electrochemistry domain: the shared semantics of the battery figure families.

``schema.py``  holds the input contract both families share (header aliases, Branch
enumeration, Cycle rules, numeric validation); ``naming.py`` holds the sample-name
rules.  Each family owns a sub-package with its ``ingest`` loader and its ``plan``
builder.
"""
