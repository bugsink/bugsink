from django.db import models


class Chunk(models.Model):
    checksum = models.CharField(max_length=40, unique=True)  # unique implies index, which we also use for lookups
    size = models.PositiveIntegerField()
    data = models.BinaryField(null=False)  # as with Events, we can "eventually" move this out of the database

    def __str__(self):
        return self.checksum


class File(models.Model):
    # NOTE: since we do single-chunk uploads, optimizations are imaginable. Make it work first though

    checksum = models.CharField(max_length=40, unique=True)  # unique implies index, which we also use for lookups

    # the filename is not unique, nor meaningful in the sense that you could use it to identify the file. It is only
    # here for convenience, i.e. to eye-ball the file in a list. note that we store by checksum, and the filename gets
    # associated on the first successful store. i.e. it's possible that a file would be stored again with a different
    # name but that would go undetected by us. all that is to say: convenience thingie without strong guarantees.
    filename = models.CharField(max_length=255)

    size = models.PositiveIntegerField()
    data = models.BinaryField(null=False)  # as with Events, we can "eventually" move this out of the database

    def __str__(self):
        return self.filename


class FileMetadata(models.Model):
    file = models.ForeignKey(File, null=False, on_delete=models.CASCADE, related_name="metadatas")

    # debug_id & file_type nullability: such data exists in manifest.json; we are future-proof for it although we
    # currently don't store it as such.
    debug_id = models.UUIDField(max_length=40, null=True, blank=True)
    file_type = models.CharField(max_length=255, null=True, blank=True)
    data = models.TextField()  # we just dump the rest in here; let's see how much we really need.

    def __str__(self):
        # somewhat useless when debug_id is None; but that's not the case we care about ATM
        return f"debug_id: {self.debug_id} ({self.file_type})"

    class Meta:
        # it's _imaginable_ that the below does not actually hold (we just trust the CLI, after all), but that wouldn't
        # make any sense, so we just enforce a property that makes sense. Pro: lookups work. Con: if the client sends
        # garbage, this is not exposed.
        unique_together = (("debug_id", "file_type"),)
