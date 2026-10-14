import os
import time
import requests
import streamlit as st
from openai import OpenAI

# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="AI Project Report Generator",
    page_icon="📘",
    layout="wide"
)

st.title("📘 AI Project Report Generator")
st.write(
    "Search academic research and generate project report chapters using AI."
)

# --------------------------------------------------
# SECRETS AND CONFIGURATION
# --------------------------------------------------

try:
    OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = st.secrets.get(
        "OPENAI_MODEL",
        "gpt-4.1-mini"
    )
except Exception:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

OPENALEX_URL = "https://api.openalex.org/works"


# --------------------------------------------------
# ABSTRACT EXTRACTION
# --------------------------------------------------

def decode_abstract(inverted_index):
    if not inverted_index:
        return "Abstract not available."

    try:
        words = []

        for word, positions in inverted_index.items():
            for position in positions:
                words.append((position, word))

        words.sort(key=lambda item: item[0])

        return " ".join(word for _, word in words)

    except (AttributeError, TypeError, ValueError):
        return "Abstract not available."


# --------------------------------------------------
# OPENALEX SEARCH WITH RATE-LIMIT RETRIES
# --------------------------------------------------

def search_research(search_topic, max_results=10):
    params = {
        "search": search_topic,
        "per-page": max_results,
        "sort": "relevance_score:desc"
    }

    response = None

    for attempt in range(3):
        response = requests.get(
            OPENALEX_URL,
            params=params,
            timeout=30,
            headers={
                "User-Agent": "AIProjectReportGenerator/1.0"
            }
        )

        if response.status_code != 429:
            break

        if attempt < 2:
            time.sleep(5 * (attempt + 1))

    response.raise_for_status()
    data = response.json()

    results = []

    for work in data.get("results", []):
        authors = []

        for authorship in work.get("authorships", []):
            author = authorship.get("author", {})
            name = author.get("display_name")

            if name:
                authors.append(name)

        doi = work.get("doi")
        openalex_id = work.get("id")

        results.append({
            "Title": work.get("title") or "Untitled research paper",
            "Authors": ", ".join(authors) or "Authors not listed",
            "Year": work.get("publication_year") or "Unknown",
            "Abstract": decode_abstract(
                work.get("abstract_inverted_index")
            ),
            "DOI": doi or "",
            "URL": doi or openalex_id or ""
        })

    return results


# --------------------------------------------------
# OPENAI CHAPTER GENERATION
# --------------------------------------------------

def generate_chapter(
    project_title,
    chapter_name,
    research_context
):
    if not OPENAI_API_KEY:
        raise ValueError(
            "OpenAI API key is missing from Streamlit Secrets."
        )

    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
You are an academic project report writing assistant.

Project title:
{project_title}

Chapter:
{chapter_name}

Research sources:
{research_context}

Write a clear, formal academic chapter with suitable headings.

Requirements:
- Use the supplied research sources where relevant.
- Do not invent authors, papers, citations, statistics, or results.
- Clearly identify limitations when information is insufficient.
- Distinguish proposed work from experiments already completed.
- Do not claim that the user performed experiments unless stated.
- Finish with a short chapter conclusion.
- Make the writing appropriate for an academic project report.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=prompt
    )

    return response.output_text


# --------------------------------------------------
# SIDEBAR SETTINGS
# --------------------------------------------------

st.sidebar.header("⚙️ Report Settings")

max_results = st.sidebar.selectbox(
    "Number of research papers",
    [5, 10, 15, 20],
    index=1
)

chapter_options = [
    "Abstract",
    "Introduction",
    "Literature Review",
    "Problem Statement",
    "Objectives",
    "Proposed Methodology",
    "Expected Results",
    "Conclusion",
    "Future Scope"
]

selected_chapters = st.sidebar.multiselect(
    "Select report chapters",
    chapter_options,
    default=[
        "Abstract",
        "Introduction",
        "Literature Review",
        "Problem Statement",
        "Objectives",
        "Proposed Methodology",
        "Conclusion"
    ]
)


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "research_results" not in st.session_state:
    st.session_state.research_results = []

if "last_search_topic" not in st.session_state:
    st.session_state.last_search_topic = ""

if "generated_chapters" not in st.session_state:
    st.session_state.generated_chapters = {}


# --------------------------------------------------
# PROJECT DETAILS
# --------------------------------------------------

st.header("1. Project Details")

project_title = st.text_input(
    "Project title",
    placeholder="Artificial Intelligence in Manufacturing"
)

search_topic = st.text_input(
    "Research topic",
    placeholder="AI applications in manufacturing"
)

search_button = st.button(
    "🔎 Search Research Sources",
    type="primary"
)


# --------------------------------------------------
# SEARCH RESEARCH SOURCES
# --------------------------------------------------

if search_button:
    if not search_topic.strip():
        st.warning("Please enter a research topic.")

    else:
        with st.spinner("Searching academic research sources..."):
            try:
                results = search_research(
                    search_topic.strip(),
                    max_results
                )

                st.session_state.research_results = results
                st.session_state.last_search_topic = search_topic.strip()

                if results:
                    st.success(
                        f"Found {len(results)} research sources."
                    )
                else:
                    st.info(
                        "No results found. Try a broader search topic."
                    )

            except requests.HTTPError as error:
                status = (
                    error.response.status_code
                    if error.response is not None
                    else "unknown"
                )

                if status == 429:
                    st.error(
                        "OpenAlex is rate-limiting requests (HTTP 429). "
                        "Wait a few minutes before trying again."
                    )
                else:
                    st.error(
                        f"OpenAlex returned HTTP status {status}."
                    )

            except requests.Timeout:
                st.error(
                    "The OpenAlex request timed out. Please try again later."
                )

            except requests.ConnectionError:
                st.error(
                    "Could not connect to OpenAlex. Check your connection "
                    "or try again later."
                )

            except requests.RequestException as error:
                st.error(
                    f"Research request failed: {type(error).__name__}"
                )

            except Exception as error:
                st.error(
                    f"Unexpected error: {type(error).__name__}"
                )


# --------------------------------------------------
# DISPLAY RESEARCH SOURCES
# --------------------------------------------------

if st.session_state.research_results:
    st.header("2. Research Sources")

    st.caption(
        f"Search topic: {st.session_state.last_search_topic}"
    )

    for index, paper in enumerate(
        st.session_state.research_results,
        start=1
    ):
        with st.expander(
            f"{index}. {paper['Title']} ({paper['Year']})"
        ):
            st.write(f"**Authors:** {paper['Authors']}")
            st.write(f"**Year:** {paper['Year']}")
            st.write("**Abstract:**")
            st.write(paper["Abstract"])

            if paper["DOI"]:
                st.markdown(
                    f"**DOI:** [{paper['DOI']}]({paper['DOI']})"
                )
            elif paper["URL"]:
                st.markdown(
                    f"**OpenAlex record:** [{paper['URL']}]"
                    f"({paper['URL']})"
                )


# --------------------------------------------------
# GENERATE REPORT CHAPTERS
# --------------------------------------------------

st.header("3. Generate Project Report")

if not OPENAI_API_KEY:
    st.warning(
        "OpenAI API key is not configured. Add OPENAI_API_KEY "
        "in Streamlit Cloud → App settings → Secrets."
    )

if st.button(
    "✨ Generate Selected Chapters",
    type="primary"
):
    if not project_title.strip():
        st.warning("Please enter your project title.")

    elif not selected_chapters:
        st.warning("Please select at least one chapter.")

    elif not st.session_state.research_results:
        st.warning(
            "Search for research sources before generating chapters."
        )

    elif not OPENAI_API_KEY:
        st.error(
            "OpenAI API key is missing. Configure it in Streamlit Secrets."
        )

    else:
        research_context = "\n\n".join(
            [
                (
                    f"Title: {paper['Title']}\n"
                    f"Authors: {paper['Authors']}\n"
                    f"Year: {paper['Year']}\n"
                    f"DOI: {paper['DOI'] or 'Not listed'}\n"
                    f"Abstract: {paper['Abstract']}"
                )
                for paper in st.session_state.research_results
            ]
        )

        generated = {}
        failed = []

        progress = st.progress(0)
        status_text = st.empty()

        for index, chapter in enumerate(selected_chapters):
            status_text.write(
                f"Generating: {chapter}..."
            )

            try:
                generated[chapter] = generate_chapter(
                    project_title.strip(),
                    chapter,
                    research_context
                )

            except Exception as error:
                failed.append(
                    f"{chapter}: {type(error).__name__}"
                )

            progress.progress(
                (index + 1) / len(selected_chapters)
            )

        st.session_state.generated_chapters = generated

        status_text.empty()
        progress.empty()

        if generated:
            st.success(
                f"Generated {len(generated)} chapter(s)."
            )

        if failed:
            st.warning(
                "Some chapters could not be generated:\n\n"
                + "\n".join(failed)
            )


# --------------------------------------------------
# DISPLAY AND DOWNLOAD REPORT
# --------------------------------------------------

if st.session_state.generated_chapters:
    st.header("4. Generated Report")

    report_parts = []

    for chapter, content in (
        st.session_state.generated_chapters.items()
    ):
        with st.expander(chapter, expanded=True):
            st.markdown(content)

            st.download_button(
                label=f"⬇️ Download {chapter}",
                data=content,
                file_name=(
                    chapter.lower().replace(" ", "_") + ".txt"
                ),
                mime="text/plain",
                key=f"download_{chapter}"
            )

        report_parts.append(
            f"# {chapter}\n\n{content}"
        )

    complete_report = (
        f"# {project_title.strip()}\n\n"
        + "\n\n".join(report_parts)
    )

    st.download_button(
        label="📄 Download Complete Report (.txt)",
        data=complete_report,
        file_name="project_report.txt",
        mime="text/plain",
        type="primary"
    )


# --------------------------------------------------
# FOOTER
# --------------------------------------------------

st.divider()

st.caption(
    "AI Project Report Generator | Verify research sources and "
    "review AI-generated content before academic submission."
)
```
