from depscope.identity.coordinates import normalized_name

PUBLIC_ROOTS = (
    "langchain",
    "langchain-core",
    "langchain-community",
    "langchain-experimental",
    "langgraph",
    "langsmith",
    "transformers",
    "sentence-transformers",
    "datasets",
    "huggingface-hub",
    "mlflow",
    "gradio",
    "streamlit",
    "chromadb",
    "llama-index",
)


def family_name(package):
    name = normalized_name(package)
    return "langchain_family" if name in PUBLIC_ROOTS[:6] else name


def missing_years(metadata, cutoff):
    # Reuse the fixed release selection, without substituting unsuccessful versions.
    from datetime import UTC, datetime

    from packaging.version import InvalidVersion, Version

    years = set()
    for name, files in metadata.get("releases", {}).items():
        try:
            version = Version(name)
            if version.is_prerelease or version.is_devrelease:
                continue
        except InvalidVersion:
            continue
        dates = []
        for file in files:
            if file.get("yanked"):
                continue
            try:
                date = datetime.fromisoformat(file["upload_time_iso_8601"])
                if date.tzinfo is not None and date <= cutoff:
                    dates.append(date.astimezone(UTC))
            except (KeyError, ValueError, TypeError):
                continue
        if dates:
            years.add(min(dates).year)
    return tuple(year for year in (2024, 2025) if year not in years)
