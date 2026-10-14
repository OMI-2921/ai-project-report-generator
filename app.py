import os
import time
import re
import html
import requests
import streamlit as st
from openai import OpenAI

# ==================================================
# 1. PAGE CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="AI Project Report Generator",
    page_icon="📘",
    layout="wide"
)

st.title("📘 AI Project Report Generator")
st.write(
    "Search academic papers, review research sources, "
    "and generate project report chapters using AI."
)

# ==================================================
# 2. CONFIGURATION
# ==================================================

try:
    OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = st.secrets.get(
        "OPENAI_MODEL",
        "gpt-4.1-mini"
    )
except Exception:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv(
        "OPENAI_MODEL",
        "gpt-4.1-mini"
    )

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"

HEADERS = {
    "User-Agent": "AIProjectReportGenerator/1.0"
}

# ==================================================
# 3. ABSTRACT HELPERS
# ==================================================

def decode_abstract(inverted_index):
    """Decode the inverted-index format used by OpenAlex."""

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


def clean_abstract(text):
    """Remove HTML tags from abstracts returned by Crossref."""

    if not text:
        return "Abstract not available."

    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    return text or "Abstract not available."


# ==================================================
# 4. OPENALEX SEARCH
# ==================================================

def search_openalex(topic, max_results):
    params = {
        "search": topic,
        "per-page": max_results,
        "sort": "relevance_score:desc"
    }

    response = None

    for attempt in range(2):
        response = requests.get(
            OPENALEX_URL,
            params=params,
            headers=HEADERS,
            timeout=25
        )

        if response.status_code != 429:
            break

        if attempt == 0:
            time.sleep(5)

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

        doi = work.get("doi") or ""
        record_url = work.get("id") or doi

        results.append({
            "Title": work.get("title") or "Untitled paper",
            "Authors": ", ".join(authors) or "Not listed",
            "Year": work.get("publication_year") or "Unknown",
            "Abstract": decode_abstract(
                work.get("abstract_inverted_index")
            ),
            "DOI": doi,
            "URL": record_url,
            "Source": "OpenAlex"
        })

    return results


# ==================================================
# 5. CROSSREF FALLBACK SEARCH
# ==================================================

def search_crossref(topic, max_results):
    """Use Crossref if OpenAlex is rate-limiting requests."""

    response = requests.get(
        CROSSREF_URL,
        params={
            "query": topic,
            "rows": max_results,
            "select": (
                "title,author,published,created,DOI,"
                "URL,abstract,type"
            )
        },
        headers=HEADERS,
        timeout=25
    )

    response.raise_for_status()

    data = response.json()
    items = data.get("message", {}).get("items", [])

    results = []

    for item in items:
        titles = item.get("title", [])
        title = titles[0] if titles else "Untitled paper"

        authors = []

        for author in item.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            name = f"{given} {family}".strip()

            if name:
                authors.append(name)

        date_parts = (
            item.get("published", {})
            .get("date-parts", [[]])
        )

        year = (
            date_parts[0][0]
            if date_parts and date_parts[0]
            else "Unknown"
        )

        doi_value = item.get("DOI", "")
        doi_url = (
            f"https://doi.org/{doi_value}"
            if doi_value else ""
        )

        results.append({
            "Title": title,
            "Authors": ", ".join(authors) or "Not listed",
            "Year": year,
            "Abstract": clean_abstract(
                item.get("abstract", "")
            ),
            "DOI": doi_url,
            "URL": item.get("URL") or doi_url,
            "Source": "Crossref"
        })

    return results


# ==================================================
# 6. COMBINED RESEARCH SEARCH
# ==================================================

def search_research(topic, max_results=10):
    try:
        return search_openalex(topic, max_results)

    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status != 429:
            raise

        # OpenAlex rate limit: try the alternative source.
        try:
            results = search_crossref(topic, max_results)

            if results:
                return results

            raise RuntimeError(
                "Crossref returned no research results."
            )

        except requests.RequestException as fallback_error:
            raise RuntimeError(
                "OpenAlex is rate-limiting requests and "
                "Crossref could not be reached. Please wait "
                "and try again later."
            ) from fallback_error


# ==================================================
# 7. AI CHAPTER GENERATION
# ==================================================

def generate_chapter(
    project_title,
    chapter_name,
    research_context,
    extra_instructions=""
):
    if not OPENAI_API_KEY:
        raise ValueError(
            "OpenAI API key is missing from Streamlit Secrets."
        )

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=90,
        max_retries=2
    )

    prompt = f"""
You are an academic project report writing assistant.

PROJECT TITLE:
{project_title}

CHAPTER:
{chapter_name}

ADDITIONAL INSTRUCTIONS:
{extra_instructions or "No additional instructions."}

RESEARCH SOURCES:
{research_context}

WRITING REQUIREMENTS:
1. Write in formal, clear academic English.
2. Use suitable headings and subheadings.
3. Use the supplied research sources where relevant.
4. Never invent papers, authors, citations, statistics, or results.
5. Do not claim experiments have been completed unless evidence
   has been supplied.
6. Clearly identify assumptions and information gaps.
7. Make the chapter relevant to the project title.
8. End with an appropriate concluding section.
9. Do not fabricate a bibliography. Identify source details
   only when those details are available in the supplied data.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=prompt
    )

    content = response.output_text

    if not content:
        raise RuntimeError(
            "The AI service returned an empty response."
        )

    return content


# ==================================================
# 8. SIDEBAR
# ==================================================

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
    "System Design",
    "Implementation",
    "Expected Results",
    "Conclusion",
    "Future Scope"
]

default_chapters = [
    "Abstract",
    "Introduction",
    "Literature Review",
    "Problem Statement",
    "Objectives",
    "Proposed Methodology",
    "Conclusion"
]

selected_chapters = st.sidebar.multiselect(
    "Select report chapters",
    chapter_options,
    default=default_chapters
)

extra_instructions = st.sidebar.text_area(
    "Additional instructions (optional)",
    placeholder=(
        "Example: Focus on manufacturing applications "
        "and keep the language suitable for a final-year project."
    )
)

# ==================================================
# 9. SESSION STATE
# ==================================================

if "research_results" not in st.session_state:
    st.session_state.research_results = []

if "last_search_topic" not in st.session_state:
    st.session_state.last_search_topic = ""

if "generated_chapters" not in st.session_state:
    st.session_state.generated_chapters = {}

if "last_project_title" not in st.session_state:
    st.session_state.last_project_title = ""


# ==================================================
# 10. PROJECT DETAILS
# ==================================================

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


# ==================================================
# 11. SEARCH BUTTON
# ==================================================

if search_button:
    if not search_topic.strip():
        st.warning("Please enter a research topic.")

    else:
        with st.spinner(
            "Searching academic research sources..."
        ):
            try:
                results = search_research(
                    search_topic.strip(),
                    max_results
                )

                st.session_state.research_results = results
                st.session_state.last_search_topic = (
                    search_topic.strip()
                )

                # Clear old chapters when the sources change.
                st.session_state.generated_chapters = {}

                if results:
                    source = results[0]["Source"]

                    st.success(
                        f"Found {len(results)} research sources. "
                        f"Source: {source}."
                    )

                    if source == "Crossref":
                        st.info(
                            "OpenAlex was rate-limiting requests, "
                            "so results were retrieved from Crossref."
                        )
                else:
                    st.info(
                        "No results found. Try a broader topic."
                    )

            except requests.Timeout:
                st.error(
                    "The research request timed out. "
                    "Please try again later."
                )

            except requests.ConnectionError:
                st.error(
                    "Could not connect to the research service. "
                    "Check the connection or try again later."
                )

            except requests.HTTPError as error:
                status = (
                    error.response.status_code
                    if error.response is not None
                    else "unknown"
                )

                st.error(
                    f"The research service returned HTTP {status}."
                )

            except Exception as error:
                st.error(
                    f"Research search failed: {type(error).__name__}: "
                    f"{str(error)}"
                )


# ==================================================
# 12. DISPLAY RESEARCH SOURCES
# ==================================================

if st.session_state.research_results:
    st.header("2. Research Sources")

    st.caption(
        f"Topic: {st.session_state.last_search_topic}"
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
            st.write(f"**Source:** {paper['Source']}")
            st.write("**Abstract:**")
            st.write(paper["Abstract"])

            if paper["DOI"]:
                st.markdown(
                    f"**DOI:** [{paper['DOI']}]({paper['DOI']})"
                )
            elif paper["URL"]:
                st.markdown(
                    f"**Research record:** [{paper['URL']}]"
                    f"({paper['URL']})"
                )


# ==================================================
# 13. GENERATE REPORT
# ==================================================

st.header("3. Generate Project Report")

if not OPENAI_API_KEY:
    st.warning(
        "OpenAI API key is not configured. Add OPENAI_API_KEY "
        "in Streamlit Cloud → App settings → Secrets."
    )

generate_button = st.button(
    "✨ Generate Selected Chapters",
    type="primary"
)

if generate_button:
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
            "OpenAI API key is missing from Streamlit Secrets."
        )

    else:
        research_context = "\n\n".join(
            (
                f"Title: {paper['Title']}\n"
                f"Authors: {paper['Authors']}\n"
                f"Year: {paper['Year']}\n"
                f"DOI: {paper['DOI'] or 'Not listed'}\n"
                f"Source: {paper['Source']}\n"
                f"Abstract: {paper['Abstract']}"
            )
            for paper in st.session_state.research_results
        )

        generated = {}
        failed = []

        progress = st.progress(0)
        status_text = st.empty()

        for index, chapter in enumerate(selected_chapters):
            status_text.write(
                f"Generating chapter: {chapter}..."
            )

            try:
                generated[chapter] = generate_chapter(
                    project_title.strip(),
                    chapter,
                    research_context,
                    extra_instructions
                )

            except Exception as error:
                failed.append(
                    f"{chapter}: {type(error).__name__}: {str(error)}"
                )

            progress.progress(
                (index + 1) / len(selected_chapters)
            )

        progress.empty()
        status_text.empty()

        st.session_state.generated_chapters = generated
        st.session_state.last_project_title = project_title.strip()

        if generated:
            st.success(
                f"Successfully generated {len(generated)} chapter(s)."
            )

        if failed:
            st.warning(
                "Some chapters could not be generated:\n\n"
                + "\n".join(failed)
            )


# ==================================================
# 14. DISPLAY AND DOWNLOAD REPORT
# ==================================================

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
        f"# {st.session_state.last_project_title}\n\n"
        + "\n\n".join(report_parts)
    )

    st.download_button(
        label="📄 Download Complete Report (.txt)",
        data=complete_report,
        file_name="project_report.txt",
        mime="text/plain",
        type="primary"
    )


# ==================================================
# 15. FOOTER
# ==================================================

st.divider()

st.caption(
    "AI Project Report Generator | Review AI-generated content "
    "and verify research sources before academic submission."
)
