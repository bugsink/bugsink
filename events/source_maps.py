import pdbparse
import io
from os.path import basename
from datetime import datetime, timezone
from uuid import UUID
import json
import ecma426
from issues.utils import get_values
from bugsink.transaction import delay_on_commit
from compat.timestamp import format_timestamp
from files.models import FileMetadata
from files.tasks import record_file_accesses
import logging

# Dijkstra, Sourcemaps and Python lists start at 0, but editors and our UI show lines starting at 1.
FROM_DISPLAY = -1
TO_DISPLAY = 1

logger = logging.getLogger("bugsink.issues")

class SourceMaps:
    @staticmethod
    def apply_source_map_global(parsed_data):
        """
        Apply source maps to parsed event data based on platform.
        """
        platform = getattr(parsed_data, "platform", None)
        if not platform:
            return parsed_data

        method_name = "apply_source_map_" + platform.lower()
        method = getattr(SourceMaps, method_name, None)

        if not method:
            # No mapping available for this platform
            return parsed_data

        return method(parsed_data)

    @staticmethod
    def apply_source_map_csharp(parsed_data):
        """
        Handle mapping of exception stack traces from DLL+PDB back to source lines.
        """
        exceptions = parsed_data.get("exceptions", [])

        # Get all available PDB files
        pdb_files_set = FileMetadata.objects.filter(file_type="pdb").select_related("file")
        pdb_files = list(pdb_files_set)

        for exception in exceptions:
            frames = exception.get("stacktrace", {}).get("frames", [])
            for frame in frames:
                dll_name = frame.get("filename")  # DLL/EXE name from stack trace
                line = frame.get("lineno")

                if not dll_name or not line:
                    continue

                # Step 1: filter pdbs by matching dll/exe basename
                matching_pdbs = [pf for pf in pdb_files if
                                 dll_name.lower().startswith(pf.file.filename.lower().replace(".pdb", ""))]

                for pdb_meta in matching_pdbs:
                    try:
                        # Step 2: Verify PDB GUID+Age matches DLL
                        if not pdb_matches_dll(pdb_meta.file.data, dll_name):
                            continue  # skip mismatched pdb

                        # Step 3: Lookup mapping in correct PDB
                        original_line, original_method, status = lookup_line_in_pdb_filedata(
                            pdb_meta.file.data, line
                        )
                        if status:
                            if original_line:
                                frame["lineno"] = original_line
                            if original_method:
                                frame["function"] = original_method
                            break  # stop once we found a valid mapping
                    except Exception as e:
                        logger.error(f"PDB lookup failed for {dll_name}: {e}")

        return parsed_data

    @staticmethod
    def apply_source_map_javascript(parsed_data):
        images = parsed_data.get("debug_meta", {}).get("images", [])
        if not images:
            return

        debug_id_for_filename = {
            image["code_file"]: UUID(image["debug_id"])
            for image in images
            if "debug_id" in image and "code_file" in image and image["type"] == "sourcemap"
        }

        metadata_obj_lookup = {
            metadata_obj.debug_id: metadata_obj
            for metadata_obj in FileMetadata.objects.filter(
                debug_id__in=debug_id_for_filename.values(), file_type="source_map").select_related("file")
        }

        metadata_ids = [metadata_obj.id for metadata_obj in metadata_obj_lookup.values()]
        delay_on_commit(record_file_accesses, metadata_ids, format_timestamp(datetime.now(timezone.utc)))

        filenames_with_metas = [
            (filename, metadata_obj_lookup[debug_id])
            for (filename, debug_id) in debug_id_for_filename.items()
            if debug_id in metadata_obj_lookup  # if not: sourcemap not uploaded
        ]

        sourcemap_for_filename = {
            filename: ecma426.loads(_postgres_fix(meta.file.data))
            for (filename, meta) in filenames_with_metas
        }

        source_for_filename = {}
        for filename, meta in filenames_with_metas:
            sm_data = json.loads(_postgres_fix(meta.file.data))

            sources = sm_data.get("sources", [])
            sources_content = sm_data.get("sourcesContent", [])

            for (source_file_name, source_file) in zip(sources, sources_content):
                source_for_filename[source_file_name] = source_file.splitlines()

        for exception in get_values(parsed_data.get("exception", {})):
            for frame in exception.get("stacktrace", {}).get("frames", []):
                # NOTE: try/except in the loop would allow us to selectively skip frames that we fail to process

                if frame.get("filename") in sourcemap_for_filename:
                    sm = sourcemap_for_filename[frame["filename"]]

                    mapping = sm.lookup_left(frame["lineno"] + FROM_DISPLAY, frame["colno"])

                    if mapping.source in source_for_filename:
                        lines = source_for_filename[mapping.source]

                        frame["pre_context"] = lines[max(0, mapping.original_line - 5):mapping.original_line]
                        frame["context_line"] = lines[mapping.original_line]
                        frame["post_context"] = lines[mapping.original_line + 1:mapping.original_line + 5]
                        frame["lineno"] = mapping.original_line + TO_DISPLAY
                        frame['filename'] = mapping.source
                        frame['function'] = mapping.name
                        # frame["colno"] = mapping.original_column + TO_DISPLAY  not actually used

                elif frame.get("filename") in debug_id_for_filename:
                    # The event_data reports that a debug_id is available for this filename, but we don't have it; this
                    # could be because the sourcemap was not uploaded. We want to show the debug_id in the stacktrace as
                    # a hint to the user that they should upload the sourcemap.
                    frame["debug_id"] = str(debug_id_for_filename[frame["filename"]])

    @staticmethod
    def get_sourcemap_images(event_data):
        # NOTE: butchered copy/paste of apply_sourcemaps; refactoring for DRY is a TODO
        images = event_data.get("debug_meta", {}).get("images", [])
        if not images:
            return []

        debug_id_for_filename = {
            image["code_file"]: UUID(image["debug_id"])
            for image in images
            if "debug_id" in image and "code_file" in image and image["type"] == "sourcemap"
        }

        metadata_obj_lookup = {
            metadata_obj.debug_id: metadata_obj
            for metadata_obj in FileMetadata.objects.filter(
                debug_id__in=debug_id_for_filename.values(), file_type="source_map").select_related("file")
        }

        return [
            (basename(filename),
             f"{debug_id} " + (" (uploaded)" if debug_id in metadata_obj_lookup else " (not uploaded)"))
            for filename, debug_id in debug_id_for_filename.items()
        ]





def lookup_line_in_pdb_filedata(pdb_filedata, line_number):
    """
    Given a PDB file's raw bytes and a DLL line number,
    return the original source line and method.
    Uses `pdbparse` to query symbol info.
    """
    try:
        # Wrap bytes in BytesIO so pdbparse can read it like a file
        pdb_stream = io.BytesIO(pdb_filedata)
        pdb = pdbparse.parse_stream(pdb_stream)

        # Walk symbols to try to find the closest line info
        for module in pdb.streams.values():
            if hasattr(module, "symbols"):
                for sym in module.symbols:
                    if getattr(sym, "address", None) == line_number:
                        return getattr(sym, "lineno", line_number), getattr(sym, "name", "<unknown_method>"), True

        # Fallback: return line number as-is
        return line_number, "<method_unknown>", False

    except Exception as e:
        # Fallback in case parsing fails
        return line_number, f"<pdb_lookup_failed: {e}>", False



def _postgres_fix(memoryview_or_bytes):
    if isinstance(memoryview_or_bytes, memoryview):
        # This is a workaround for the fact that some versions of psycopg return a memoryview instead of bytes;
        # see https://code.djangoproject.com/ticket/27813. This problem will go away "eventually", but here's the fix
        # till then (psycopg>=3.0.17 is OK)
        return bytes(memoryview_or_bytes)
    return memoryview_or_bytes

def pdb_matches_dll(pdb_bytes, dll_path):
    """
    Verify if a PDB matches a given DLL by comparing GUID+Age.
    """
    import pefile
    import io
    import pdbparse


    pe = pefile.PE(dll_path)
    for dbg in pe.DIRECTORY_ENTRY_DEBUG:
        if dbg.struct.Type == 2:  # IMAGE_DEBUG_TYPE_CODEVIEW
            data = pe.get_memory_mapped_image()[dbg.struct.AddressOfRawData : dbg.struct.AddressOfRawData + dbg.struct.SizeOfData]
            guid = data[4:20]   # CodeView GUID
            age = int.from_bytes(data[20:24], "little")
            pdb_path = data[24:].decode("utf-8").rstrip("\x00")


    pdb = pdbparse.parse_stream(io.BytesIO(pdb_bytes))
    hdr = pdb.streams[1].header  # PDB header contains GUID+Age
    pdb_guid = hdr.Signature
    pdb_age = hdr.Age

    return guid == pdb_guid and age == pdb_age
