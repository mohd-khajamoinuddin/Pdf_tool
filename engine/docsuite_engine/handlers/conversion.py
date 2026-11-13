from __future__ import annotations

from pathlib import Path

from .. import convert
from ..convert.basic import images_to_pdf
from ..rpc import Context, EngineError, method
from ..util import atomic_output, in_path, out_dir


@method("convert.list")
def convert_list(params, ctx):
    return convert.supported()


@method("convert.run")
def convert_run(params, ctx):
    """{input, output, options?} - the converter is chosen from the two extensions."""
    return convert.run(in_path(params), Path(str(params["output"])), params.get("options"), ctx)


@method("convert.batch")
def convert_batch(params, ctx):
    """{inputs, output_dir, target, options?} - one failure does not stop the batch."""
    inputs = [Path(str(p)) for p in params["inputs"]]
    if not inputs:
        raise EngineError("bad_params", "No input files given")
    target = convert.norm_ext(str(params["target"]))
    folder = out_dir(params)
    results = []
    for i, src in enumerate(inputs):
        ctx.progress(i / len(inputs), src.name)
        dst = folder / f"{src.stem}.{target}"
        n = 1
        while dst.exists():  # never overwrite silently
            n += 1
            dst = folder / f"{src.stem} ({n}).{target}"
        try:
            if not src.is_file():
                raise EngineError("not_found", f"File not found: {src}")
            results.append({"input": str(src), "ok": True, **convert.run(src, dst, params.get("options"), Context())})
        except Exception as exc:  # noqa: BLE001 - reported per file
            results.append({"input": str(src), "ok": False, "error": getattr(exc, "message", None) or str(exc)})
    ctx.progress(1.0, "done")
    return {
        "output_dir": str(folder),
        "succeeded": sum(r["ok"] for r in results),
        "failed": sum(not r["ok"] for r in results),
        "results": results,
    }


@method("convert.images_to_pdf")
def convert_images_to_pdf(params, ctx):
    """{inputs, output} - many images into one PDF, one image per page."""
    sources = [in_path({"input": p}) for p in params["inputs"]]
    output = Path(str(params["output"]))
    with atomic_output(output) as tmp:
        details = images_to_pdf(sources, tmp, ctx)
    return {"output": str(output), **details}
