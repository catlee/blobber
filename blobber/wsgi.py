#!/usr/bin/env python
import tempfile
import os
import hashlib
import logging
import time

from functools import partial
from sqlalchemy import create_engine
from bottle.ext import sqlalchemy as sqlalchemy_ext
from bottle import Bottle, request, abort, response
from sqlalchemy_schema import Base, MetadataBackend

from amazons3_backend import upload_to_AmazonS3

log = logging.getLogger(__name__)

app = Bottle()


def save_request_file(fileobj, hashalgo=None):
    """
    Saves uploaded file `fileobj` and returns its filename
    """
    fd, tmpfile = tempfile.mkstemp()
    h = None
    if hashalgo:
        h = hashlib.new(hashalgo)

    try:
        nread = 0
        for block in iter(partial(fileobj.read, 1024 ** 2), ''):
            nread += len(block)
            if h:
                h.update(block)
            os.write(fd, block)
        os.close(fd)
        return tmpfile, h.hexdigest()
    except:
        os.close(fd)
        os.unlink(tmpfile)
        raise


@app.post('/blobs/:hashalgo/:blobhash')
def upload_blob(hashalgo, blobhash, meta_db):
    #TODO: limit to specific IP ranges
    data = request.files.data
    if not data.file:
        print 'miss uploaded file'
        abort(400, "Missing uploaded file")

    tmpfile, _hsh = save_request_file(data.file, hashalgo)
    try:
        if _hsh != blobhash:
            print 'invalid hash'
            abort(400, "Invalid hash")

        # determine some of the metadata
        meta_dict = {
            'blobhash': blobhash,
            'upload_time': int(time.time()),
            'upload_ip': request.remote_addr
        }

        # the rest of the metadata is taken from request
        fields = ('filename', 'filesize', 'branch', 'mimetype')
        for field in fields:
            if field not in request.forms:
                print '%s missing' % field
                abort(400, '%s missing' % field)

        # make sure no extra args get into database
        meta_dict.update({k: request.forms[k] for k in fields})

        # add an entry to the metadata table
        entry = MetadataBackend(**meta_dict)
        meta_db.add(entry)

        # add file on S3 machine
        upload_to_AmazonS3(hashalgo, blobhash, tmpfile, meta_dict['mimetype'])

        response.status = 202
    finally:
        print tmpfile
        os.unlink(tmpfile)


def main():
    from config import METADB_NAME

    cur_path = os.path.dirname(os.path.abspath(__file__))
    engine = create_engine("sqlite:////%s/%s" % (cur_path, METADB_NAME))

    plugin = sqlalchemy_ext.Plugin(
        engine,
        Base.metadata,
        keyword="meta_db",
        create=True,
        commit=True,
        use_kwargs=False,
    )
    app.install(plugin)

    app.run(host='0.0.0.0', port=8080, debug=True, reloader=True)

if __name__ == '__main__':
    main()
