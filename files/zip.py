from zipfile import ZIP_DEFLATED, ZIP_STORED
import zlib_rust as zlib


def open_zip_entry(archive, name):
    # A helper that disallows "more fancy" compression methods; such methods are supported by the zipfile module, but
    # Sentry SDKs never use them writing-side, and they have been buggy before. Unzipping is a vector for (DOS) attacks
    # so we support as few compression methods as possible.

    entry = archive.getinfo(name)
    if entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
        raise NotImplementedError("Unsupported ZIP compression method: %s" % entry.compress_type)

    stream = archive.open(entry)
    if entry.compress_type == ZIP_DEFLATED:
        # we monkey-patch the _decompressor to zlib_rust in this case (zipfile does not offer a hook)
        stream._decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        # we also have to override _seekable, because if it's True seeking would recreate the C-based decompressor
        # (we don't seek within entries anyway, but setting this to False enforces this
        # and provides defense in depth)
        stream._seekable = False
    return stream
