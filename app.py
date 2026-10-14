
import os
import re
import time
import html
import requests
import streamlit as st
from google import genai
from docx import Document
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch


# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="AI Project Report Generator",
    page_icon="📚",
    layout="wide"
)

st.title("📚 AI Project Report Generator")
st.write(
    "Search academic research, generate project report chapters "
    "using Gemini, and export your report as TXT, Word, or PDF."
)


# --------------------------------------------------
# CONFIGURATION AND SECRETS
# --------------------------------------------------

def get_setting(name, default=""):
    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value else default
    except Exception:
        return os.getenv(name, default)


GEMINI_API_KEY = get_setting("GEMINI_API_KEY")
GEMINI_MODEL = get_setting("GEMINI_MODEL", "gemini-2.5-flash")

if not GEMINI_API_KEY:
    st.error(
        "Gemini API key is missing. Open your Streamlit app settings, "
        "go to Secrets, and add GEMINI_API_KEY."
    )
    st.stop()

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as exc:
    st.error(f"Could not initialize Gemini: {exc}")
    st.stop()


# --------------------------------------------------
# RESEARCH SEARCH
# --------------------------------------------------

HEADERS = {
    "User-Agent": "AIProjectReportGenerator/1.0"
}


def decode_openalex_abstract(inverted_index):
    """Convert OpenAlex's inverted abstract index into readable text."""
    if not inverted_index:
        return ""

    words = {}

    for word, positions in inverted_index.items():
        for position in positions:
            words[position] = word

    return " ".join(
        words[position] for position in sorted(words)
    )


def search_openalex(topic, limit=6):
    url = "https://api.openalex.org/works"

    params = {
        "search": topic,
        "per-page": limit,
        "select": (
            "id,doi,title,publication_year,authorships,"
            "abstract_inverted_index,primary_location"
        )
    }

    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=25
            )

            if response.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue

            response.raise_for_status()
            payload = response.json()

            results = []

            for item in payload.get("results", []):
                authors = []

                for authorship in item.get("authorships", [])[:5]:
                    author = authorship.get("author", {})
                    name = author.get("display_name")

                    if name:
                        authors.append(name)

                location = item.get("primary_location") or {}
                source = location.get("source") or {}

                results.append({
                    "title": item.get("title") or "Untitled",
                    "year": item.get("publication_year") or "Unknown",
                    "authors": ", ".join(authors) or "Authors not listed",
                    "doi": item.get("doi") or "",
                    "url": (
                        item.get("doi")
                        or item.get("id")
                        or ""
                    ),
                    "journal": source.get("display_name", ""),
                    "abstract": decode_openalex_abstract(
                        item.get("abstract_inverted_index")
                    )
                })

            return results

        except requests.RequestException:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))

    return []


def search_crossref(topic, limit=6):
    """Fallback source if OpenAlex is temporarily unavailable."""
    url = "https://api.crossref.org/works"

    params = {
        "query": topic,
        "rows": limit
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=25
        )
        response.raise_for_status()

        items = response.json().get("message", {}).get("items", [])
        results = []

        for item in items:
            title_list = item.get("title") or []
            title = title_list[0] if title_list else "Untitled"

            author_names = []
            for author in item.get("author", [])[:5]:
                name = " ".join(
                    part for part in [
                        author.get("given", ""),
                        author.get("family", "")
                    ] if part
                )
                if name:
                    author_names.append(name)

            date_parts = (
                item.get("published", {}).get("date-parts")
                or item.get("created", {}).get("date-parts")
                or []
            )

            year = (
                date_parts[0][0]
                if date_parts and date_parts[0]
                else "Unknown"
            )

            doi = item.get("DOI", "")
            abstract = item.get("abstract", "")
            abstract = re.sub(r"<[^>]+>", " ", abstract)
            abstract = html.unescape(abstract)
            abstract = re.sub(r"\s+", " ", abstract).strip()

            results.append({
                "title": title,
                "year": year,
                "authors": ", ".join(author_names) or "Authors not listed",
                "doi": doi,
                "url": (
                    f"https://doi.org/{doi}"
                    if doi else item.get("URL", "")
                ),
                "journal": (
                    (item.get("container-title") or [""])[0]
                ),
                "abstract": abstract
            })

        return results

    except requests.RequestException:
        return []


def search_research(topic, limit):
    results = search_openalex(topic, limit)

    if results:
        return results, "OpenAlex"

    results = search_crossref(topic, limit)

    if results:
        return results, "Crossref"

    return [], None


# --------------------------------------------------
# REPORT CHAPTERS
# --------------------------------------------------

DEFAULT_CHAPTERS = [
    "Abstract",
    "Introduction",
    "Literature Review",
    "Problem Statement",
    "Objectives",
    "Scope of the Project",
    "Proposed Methodology",
    "System Design",
    "Expected Outcomes",
    "Conclusion",
    "References"
]


def make_source_context(papers):
    sections = []

    for index, paper in enumerate(papers, start=1):
        abstract = paper.get("abstract") or "No abstract available."
        abstract = abstract[:1800]

        sections.append(
            f"Source {index}\n"
            f"Title: {paper['title']}\n"
            f"Authors: {paper['authors']}\n"
            f"Year: {paper['year']}\n"
            f"Journal: {paper.get('journal', '')}\n"
            f"DOI or URL: {paper.get('url', '')}\n"
            f"Abstract: {abstract}\n"
        )

    return "\n".join(sections)


def generate_chapter(
    chapter,
    topic,
    project_type,
    academic_level,
    word_count,
    instructions,
    source_context
):
    prompt = f"""
You are an academic project-report writing assistant.

Write the report chapter: {chapter}

PROJECT DETAILS
Project topic: {topic}
Project type: {project_type}
Academic level: {academic_level}
Approximate target length: {word_count} words per chapter

ADDITIONAL USER INSTRUCTIONS
{instructions or "None provided."}

RESEARCH SOURCES
{source_context}

WRITING REQUIREMENTS
1. Write clear, formal academic English.
2. Keep the discussion relevant to the specified project topic.
3. Use meaningful headings and subheadings where appropriate.
4. Explain technical concepts clearly and logically.
5. Use the research information when relevant.
6. Never invent authors, publications, statistics, experiments, or findings.
7. Distinguish established evidence from proposed ideas and expectations.
8. If information is unavailable, acknowledge the limitation.
9. Do not claim that an experiment or implementation was completed unless
   the user supplied evidence that it was completed.
10. Do not fabricate citations. Use only the supplied source details.
11. For the References chapter, list only supplied research sources.
12. Output the chapter content itself, without discussing these instructions.

Generate the chapter now.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    text = response.text

    if not text or not text.strip():
        raise ValueError("Gemini returned an empty response.")

    return text.strip()


# --------------------------------------------------
# EXPORT FUNCTIONS
# --------------------------------------------------

def create_word_report(title, chapters):
    document = Document()
    document.add_heading(title, 0)

    for chapter, content in chapters.items():
        document.add_heading(chapter, level=1)

        for paragraph in content.split("\n"):
            paragraph = paragraph.strip()

            if paragraph:
                document.add_paragraph(paragraph)

    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def create_pdf_report(title, chapters):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        spaceAfter=24
    )

    story = [Paragraph(escape(title), title_style), Spacer(1, 12)]

    for chapter, content in chapters.items():
        story.append(
            Paragraph(escape(chapter), styles["Heading1"])
        )
        story.append(Spacer(1, 8))

        for paragraph in content.split("\n"):
            paragraph = paragraph.strip()

            if paragraph:
                story.append(
                    Paragraph(
                        escape(paragraph).replace("\n", "<br/>"),
                        styles["BodyText"]
                    )
                )
                story.append(Spacer(1, 7))

        story.append(Spacer(1, 12))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def report_as_text(title, chapters):
    parts = [title, "=" * len(title)]

    for chapter, content in chapters.items():
        parts.extend([
            "",
            chapter.upper(),
            "-" * len(chapter),
            content
        ])

    return "\n".join(parts)


# --------------------------------------------------
# USER INTERFACE
# --------------------------------------------------

st.subheader("1. Project details")

with st.form("project_form"):
    topic = st.text_input(
        "Project topic",
        placeholder="e.g. AI-based disease prediction system"
    )

    col1, col2 = st.columns(2)

    with col1:
        project_type = st.selectbox(
            "Project type",
            [
                "Research Project",
                "Software Development",
                "Engineering Project",
                "Business Project",
                "Data Science Project",
                "Literature Review",
                "Other"
            ]
        )

        academic_level = st.selectbox(
            "Academic level",
            [
                "Diploma",
                "Undergraduate",
                "Postgraduate",
                "Research Scholar",
                "General"
            ]
        )

    with col2:
        research_count = st.slider(
            "Number of research sources",
            min_value=3,
            max_value=10,
            value=6
        )

        word_count = st.selectbox(
            "Approximate words per chapter",
            [300, 500, 700, 1000],
            index=1
        )

    instructions = st.text_area(
        "Additional instructions (optional)",
        placeholder=(
            "Mention your required format, technology, "
            "case study, or college guidelines."
        )
    )

    selected_chapters = st.multiselect(
        "Choose report chapters",
        DEFAULT_CHAPTERS,
        default=[
            "Abstract",
            "Introduction",
            "Literature Review",
            "Problem Statement",
            "Objectives",
            "Proposed Methodology",
            "Conclusion",
            "References"
        ]
    )

    submitted = st.form_submit_button(
        "🔎 Search Research and Generate Report",
        type="primary",
        use_container_width=True
    )


# --------------------------------------------------
# GENERATION WORKFLOW
# --------------------------------------------------

if submitted:
    if not topic.strip():
        st.error("Please enter your project topic.")
        st.stop()

    if not selected_chapters:
        st.error("Please select at least one report chapter.")
        st.stop()

    st.session_state.pop("generated_chapters", None)
    st.session_state.pop("project_title", None)

    with st.spinner("Searching academic research..."):
        papers, research_provider = search_research(
            topic.strip(),
            research_count
        )

    if not papers:
        st.warning(
            "The research services could not be reached right now. "
            "Check your internet connection and try again. "
            "You can retry shortly."
        )
        st.stop()

    st.success(
        f"Found {len(papers)} research records using {research_provider}."
    )

    with st.expander("View research sources", expanded=True):
        for index, paper in enumerate(papers, start=1):
            st.markdown(f"**{index}. {paper['title']}**")
            st.write(
                f"Authors: {paper['authors']} | Year: {paper['year']}"
            )

            if paper.get("url"):
                st.write(f"Source: {paper['url']}")

            if paper.get("abstract"):
                st.caption(paper["abstract"][:600])

    source_context = make_source_context(papers)

    generated_chapters = {}
    errors = []

    progress = st.progress(0)
    status = st.empty()

    for index, chapter in enumerate(selected_chapters):
        status.info(
            f"Generating chapter {index + 1} of "
            f"{len(selected_chapters)}: {chapter}"
        )

        try:
            content = generate_chapter(
                chapter=chapter,
                topic=topic.strip(),
                project_type=project_type,
                academic_level=academic_level,
                word_count=word_count,
                instructions=instructions,
                source_context=source_context
            )

            generated_chapters[chapter] = content

        except Exception as exc:
            error_text = str(exc)
            errors.append((chapter, error_text))

            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text.upper()
                or "quota" in error_text.lower()
            ):
                st.warning(
                    "Gemini may have reached its free-tier quota or "
                    "rate limit. Check your Google AI Studio usage "
                    "limits before retrying."
                )
                break

        progress.progress((index + 1) / len(selected_chapters))

    progress.progress(1.0)
    status.empty()

    if generated_chapters:
        st.session_state["generated_chapters"] = generated_chapters
        st.session_state["project_title"] = topic.strip()

        st.success(
            f"Generated {len(generated_chapters)} chapter(s) successfully."
        )

    if errors:
        with st.expander("Chapters that could not be generated"):
            for chapter, error in errors:
                st.write(f"**{chapter}:** {error[:700]}")

    if not generated_chapters:
        st.error(
            "No chapters were generated. Check the error details above, "
            "your Gemini API key, model name, and available quota."
        )


# --------------------------------------------------
# DISPLAY AND DOWNLOAD GENERATED REPORT
# --------------------------------------------------

if st.session_state.get("generated_chapters"):
    chapters = st.session_state["generated_chapters"]
    report_title = st.session_state.get(
        "project_title",
        "Project Report"
    )

    st.divider()
    st.subheader("2. Your generated report")

    for chapter, content in chapters.items():
        with st.expander(chapter, expanded=False):
            st.markdown(content)

            st.download_button(
                label=f"Download {chapter} (.txt)",
                data=content,
                file_name=(
                    re.sub(r"[^a-zA-Z0-9_-]+", "_", chapter).strip("_")
                    or "chapter"
                ) + ".txt",
                mime="text/plain",
                key=f"download_{chapter}"
            )

    full_text = report_as_text(report_title, chapters)

    st.divider()
    st.subheader("3. Download your complete report")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.download_button(
            "📄 Download TXT",
            data=full_text,
            file_name="project_report.txt",
            mime="text/plain",
            use_container_width=True
        )

    with col2:
        try:
            word_bytes = create_word_report(report_title, chapters)

            st.download_button(
                "📝 Download Word",
                data=word_bytes,
                file_name="project_report.docx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                use_container_width=True
            )
        except Exception as exc:
            st.error(f"Word export failed: {exc}")

    with col3:
        try:
            pdf_bytes = create_pdf_report(report_title, chapters)

            st.download_button(
                "📕 Download PDF",
                data=pdf_bytes,
                file_name="project_report.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        except Exception as exc:
            st.error(f"PDF export failed: {exc}")

    st.caption(
        "Review the generated report, verify the cited research, "
        "and adapt the content to your institution's requirements."
    )
