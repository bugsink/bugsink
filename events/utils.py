import json
import sourcemap
from issues.utils import get_values

from files.models import FileMetadata


# Dijkstra, Sourcemaps and Python lists start at 0, but editors and our UI show lines starting at 1.
FROM_DISPLAY = -1
TO_DISPLAY = 1


class IncompleteList(list):
    def __init__(self, lst, cnt):
        super().__init__(lst)
        self.incomplete = cnt


class IncompleteDict(dict):
    def __init__(self, dct, cnt):
        super().__init__(dct)
        self.incomplete = cnt


def annotate_with_meta(values, meta_values):
    """
    Use the meta_values (values attr of a "_meta" key) to annotate the values, in particular to add information about
    which lists/dicts have been trimmed.

    This depends on an ondocumented API of the Python Sentry SDK; we've just reverse-engineered the format of the
    "_meta" values.

    From the Sentry SDK source code, one could conclude that there are various pieces of info (I've seen "rem", "len",
    "val", and "err" mentioned as keys and "!limit" as a value) but I've not actually been able to get the Sentry SDK
    to emit records with the "!limit" value, and there are no tests for it, so I'm not sure how it's supposed to work.
    For now, I'm basing myself on what I've actually seen in the wild. (Also: I'm less worried about pruning in depth
    than in breadth, because in the case of in-depth pruning the fallback is still to repr() the remaining stuff, so
    you don't end up with silently trimmed data).

    See also:
    https://github.com/getsentry/relay/blob/b3ecbb980c63be542547cf346f433061f69c4bba/relay-protocol/src/meta.rs#L417

    The values are modified in-place.
    """

    for str_i, meta_value in meta_values.items():
        annotate_exception_with_meta(values[int(str_i)], meta_value)


def annotate_exception_with_meta(exception, meta_value):
    frames = exception.get("stacktrace", {}).get("frames", {})
    meta_frames = meta_value.get("stacktrace", {}).get("frames", {})

    for str_i, meta_frame in meta_frames.items():
        annotate_frame_with_meta(frames[int(str_i)], meta_frame)


def annotate_frame_with_meta(frame, meta_frame):
    frame["vars"] = annotate_var_with_meta(frame["vars"], meta_frame["vars"])


def annotate_var_with_meta(var, meta_var):
    """
    'var' is a (potentially trimmed) list or dict, 'meta_var' is a dict describing the trimming.
    """
    assert isinstance(var, (list, dict))

    if isinstance(var, list):
        Incomplete = IncompleteList
        at = lambda k: int(k)  # noqa; (for some reason the meta_k for list lookups is stored as a string)

    else:  # isinstance(var, dict):
        Incomplete = IncompleteDict
        at = lambda k: k  # noqa

    for meta_k, meta_v in meta_var.items():
        if meta_k == "":
            var = Incomplete(var, meta_v["len"] - len(var))
        else:
            var[at(meta_k)] = annotate_var_with_meta(var[at(meta_k)], meta_v)

    return var


def apply_sourcemaps(event_data):
    images = event_data.get("debug_meta", {}).get("images", [])
    if not images:
        return

    debug_id_for_filename = {
        image["code_file"]: image["debug_id"]
        for image in images
        if "debug_id" in image and "code_file" in image and image["type"] == "sourcemap"
    }

    metadata_obj_lookup = {
        str(metadata_obj.debug_id): metadata_obj
        for metadata_obj in FileMetadata.objects.filter(
            debug_id__in=debug_id_for_filename.values(), file_type="source_map").select_related("file")
    }

    filenames_with_metas = [
        (filename, metadata_obj_lookup[debug_id])
        for (filename, debug_id) in debug_id_for_filename.items()
        if debug_id in metadata_obj_lookup  # if not: sourcemap not uploaded
        ]

    sourcemap_for_filename = {
        filename: sourcemap.loads(meta.file.data)
        for (filename, meta) in filenames_with_metas
    }

    source_for_filename = {}
    for filename, meta in filenames_with_metas:
        sm_data = json.loads(meta.file.data)
        if "sourcesContent" not in sm_data or len(sm_data["sourcesContent"]) != 1:
            # our assumption is: 1 sourcemap, 1 source. The fact that both "sources" (a list of filenames) and
            # "sourcesContent" are lists seems to indicate that this assumption does not generally hold. But it not
            # holding does not play well with the id of debug_id, I think?
            continue

        source_for_filename[filename] = sm_data["sourcesContent"][0].splitlines()

    for exception in get_values(event_data.get("exception", {})):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            # NOTE: try/except in the loop would allow us to selectively skip frames that we fail to process

            if frame.get("filename") in sourcemap_for_filename and frame["filename"] in source_for_filename:
                sm = sourcemap_for_filename[frame["filename"]]
                lines = source_for_filename[frame["filename"]]

                token = sm.lookup(frame["lineno"] + FROM_DISPLAY, frame["colno"])

                frame["pre_context"] = lines[max(0, token.src_line - 5):token.src_line]
                frame["context_line"] = lines[token.src_line]
                frame["post_context"] = lines[token.src_line + 1:token.src_line + 5]
                frame["lineno"] = token.src_line + TO_DISPLAY
                # frame["colno"] = token.src_col + TO_DISPLAY  not actually used
