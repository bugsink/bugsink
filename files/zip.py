from zipfile import ZIP_DEFLATED, ZIP_STORED


def open_zip_entry(archive, name):
    # A helper that disallows "more fancy" compression methods; such methods are supported by the zipfile module, but
    # Sentry SDKs never use them writing-side, and they have been buggy before. Unzipping is a vector for (DOS) attacks
    # so we support as few compression methods as possible.

    entry = archive.getinfo(name)
    if entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
        raise NotImplementedError("Unsupported ZIP compression method: %s" % entry.compress_type)

    return archive.open(entry)
