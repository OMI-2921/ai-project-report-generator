import os
import re
import time
import html
from io import BytesIO
from xml.sax.saxutils import escape

import requests
import streamlit as st
from google import genai
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch


# ==================================================
# 1. PAGE CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="AI Project Report Generator",
    page_icon="📚",
    layout="wide"
)

st.title("📚 AI Project Report Generator")
st.write(
    "Search academic research, generate project report chapters "
    "with Gemini, and download your report in TXT, Word, or PDF format."
)


# ==================================================
# 2. CONFIGURATION
# ==================================================

def get_setting(name, default=""):
    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value else default
    except Exception:
        return os.getenv(name, default)


GEMINI_API_KEY = get_setting("GEMINI_API_KEY")
GEMINI_MODEL = get_setting("GEMINI_MODEL", "gemini-3.8-flash")

if not GEMINI_API_KEY:
    st.error(
        "Gemini API key not found. Add GEMINI_API_KEY in "
        "Streamlit Settings → Secrets."
    )
    st.stop()

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as exc:
    st.error(f"Could not initialize Gemini: {exc}")
    st.stop()


# ==================================================
# 3. ACADEMIC RESEARCH SEARCH
# ==================================================

HEADERS = {
    "User-Agent": "AIProjectReportGenerator/1.0"
}


def decode_abstract(inverted_index):
    if not inverted_index:
        return ""

    words = {}

    for word, positions in inverted_index.items():
        for position in positions:
            words[position] = word

    return " ".join(
        words[position] for position in sorted(words)
    )


def search_openalex(topic, limit):
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
            data = response.json()
            results = []

            for item in data.get("results", []):
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
                    "url": item.get("doi") or item.get("id") or "",
                    "journal": source.get("display_name", ""),
                    "abstract": decode_abstract(
                        item.get("abstract_inverted_index")
                    )
                })

            return results

        except requests.RequestException:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))

    return []


def search_crossref(topic, limit):
    url = "https://api.crossref.org/works"

    try:
        response = requests.get(
            url,
            params={"query": topic, "rows": limit},
            headers=HEADERS,
            timeout=25
        )
        response.raise_for_status()

        items = response.json().get("message", {}).get("items", [])
        results = []

        for item in items:
            titles = item.get("title") or []
            title = titles[0] if titles else "Untitled"

            authors = []

            for author in item.get("author", [])[:5]:
                name = " ".join(
                    part for part in (
                        author.get("given", ""),
                        author.get("family", "")
                    ) if part
                )

                if name:
                    authors.append(name)

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
                "authors": ", ".join(authors) or "Authors not listed",
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
    papers = search_openalex(topic, limit)

    if papers:
        return papers, "OpenAlex"

    papers = search_crossref(topic, limit)

    if papers:
        return papers, "Crossref"

    return [], None


# ==================================================
# 4. REPORT CHAPTERS
# ==================================================

DEFAULT_CHAPTERS = [
    "Abstract",
    "Introduction",
    "Literature Review",
    "Problem Statement",
    "Objectives",
    "Scope of the Project",
    "Proposed Methodology",
    "System Design",
    "Implementation",
    "Testing and Evaluation",
    "Expected Outcomes",
    "Conclusion",
    "References"
]


def build_source_context(papers):
    sections = []

    for index, paper in enumerate(papers, start=1):
        sections.append(
            f"SOURCE {index}\n"
            f"Title: {paper['title']}\n"
            f"Authors: {paper['authors']}\n"
            f"Year: {paper['year']}\n"
            f"Journal: {paper.get('journal', '')}\n"
            f"DOI or URL: {paper.get('url', '')}\n"
            f"Abstract: {(paper.get('abstract') or 'Not available')[:1200]}\n"
        )

    return "\n".join(sections)


def generate_all_chapters(
    topic,
    project_type,
    academic_level,
    word_count,
    instructions,
    selected_chapters,
    source_context
):
    chapter_list = "\n".join(
        f"- {chapter}" for chapter in selected_chapters
    )

    prompt = f"""
You are an experienced academic project-report writing assistant.

Write a project report about the following topic.

PROJECT TOPIC:
{topic}

PROJECT TYPE:
{project_type}

ACADEMIC LEVEL:
{academic_level}

TARGET LENGTH:
Approximately {word_count} words per chapter. Be concise if needed
to keep the entire report within a reasonable response length.

ADDITIONAL INSTRUCTIONS:
{instructions or "None supplied."}

CHAPTERS REQUIRED, IN THIS EXACT ORDER:
{chapter_list}

ACADEMIC SOURCES:
{source_context}

IMPORTANT REQUIREMENTS:
1. Write every requested chapter.
2. Separate each chapter using this exact format, with the chapter name
   matching the requested name:

<<<CHAPTER: Abstract>>>

Chapter text here.

<<<CHAPTER: Introduction>>>

Chapter text here.

Continue using the exact marker format for every requested chapter.

3. Use clear, formal academic English and useful subheadings.
4. Do not fabricate research, citations, authors, statistics, results,
   or experiments.
5. Explain the proposed approach as a proposal if implementation details
   have not been supplied.
6. Use the supplied academic sources when relevant.
7. For References, list only the supplied sources. Include their DOI or
   URL where available. Do not invent missing publication details.
8. If a source has no abstract, do not invent what its study concluded.
9. Keep each chapter relevant and avoid repeating the same paragraphs.
10. Return the report only, using the chapter markers exactly as specified.
"""

    last_error = None

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )

            text = response.text

            if not text or not text.strip():
                raise ValueError("Gemini returned an empty response.")

            return text.strip()

        except Exception as exc:
            last_error = exc
            message = str(exc).lower()

            # Retry temporary overloads only.
            if (
                ("503" in message or "unavailable" in message)
                and attempt < 2
            ):
                time.sleep(5 * (attempt + 1))
                continue

            # Do not repeatedly retry exhausted quota or invalid settings.
            raise exc

    raise last_error


def split_chapters(report_text, selected_chapters):
    pattern = r"<<<CHAPTER:\s*(.*?)\s*>>>"
    matches = list(re.finditer(pattern, report_text, flags=re.IGNORECASE))

    results = {}

    if not matches:
        return {
            "Complete Report": report_text.strip()
        }

    for index, match in enumerate(matches):
        name = match.group(1).strip()

        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(report_text)
        )

        content = report_text[start:end].strip()

        # Match requested chapter names without regard to case.
        requested_name = next(
            (
                chapter for chapter in selected_chapters
                if chapter.lower() == name.lower()
            ),
            name
        )

        if content:
            results[requested_name] = content

    # Preserve any report content even if the model used unexpected markers.
    if not results:
        return {"Complete Report": report_text.strip()}

    return results


# ==================================================
# 5. EXPORT FUNCTIONS
# ==================================================

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


def create_word_report(title, chapters):
    document = Document()
    document.add_heading(title, 0)

    for chapter, content in chapters.items():
        document.add_heading(chapter, level=1)

        for paragraph in content.splitlines():
            paragraph = paragraph.strip()

            if paragraph:
                document.add_paragraph(paragraph)

    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)

    return buffer.getvalue()


def create_pdf_report(title, chapters):
    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        spaceAfter=24
    )

    story = [
        Paragraph(escape(title), title_style),
        Spacer(1, 12)
    ]

    for chapter, content in chapters.items():
        story.append(
            Paragraph(escape(chapter), styles["Heading1"])
        )
        story.append(Spacer(1, 8))

        for paragraph in content.splitlines():
            paragraph = paragraph.strip()

            if paragraph:
                story.append(
                    Paragraph(
                        escape(paragraph),
                        styles["BodyText"]
                    )
                )
                story.append(Spacer(1, 7))

        story.append(Spacer(1, 12))

    document.build(story)
    buffer.seek(0)

    return buffer.getvalue()


# ==================================================
# 6. PROJECT INPUT FORM
# ==================================================

st.subheader("1. Enter your project details")

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
            value=5
        )

        word_count = st.selectbox(
            "Approximate words per chapter",
            [200, 300, 500, 700],
            index=2
        )

    instructions = st.text_area(
        "Additional instructions (optional)",
        placeholder=(
            "Mention required technologies, project requirements, "
            "college guidelines, or formatting instructions."
        )
    )

    selected_chapters = st.multiselect(
        "Select report chapters",
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


# ==================================================
# 7. GENERATE REPORT WITH ONE API REQUEST
# ==================================================

if submitted:
    if not topic.strip():
        st.error("Please enter a project topic.")
        st.stop()

    if not selected_chapters:
        st.error("Please select at least one chapter.")
        st.stop()

    st.session_state.pop("generated_chapters", None)
    st.session_state.pop("project_title", None)

    with st.spinner("Searching academic research..."):
        papers, provider = search_research(
            topic.strip(),
            research_count
        )

    if not papers:
        st.warning(
            "Could not retrieve research sources right now. "
            "Check your connection and try again."
        )
        st.stop()

    st.success(
        f"Found {len(papers)} research records using {provider}."
    )

    with st.expander("View research sources"):
        for index, paper in enumerate(papers, start=1):
            st.markdown(f"**{index}. {paper['title']}**")
            st.write(
                f"Authors: {paper['authors']} | Year: {paper['year']}"
            )

            if paper.get("url"):
                st.write(f"Source: {paper['url']}")

            if paper.get("abstract"):
                st.caption(paper["abstract"][:500])

    source_context = build_source_context(papers)

    progress = st.progress(0)
    status = st.empty()

    status.info(
        f"Generating {len(selected_chapters)} chapters in one Gemini request. "
        "This may take a little while."
    )

    try:
        report_text = generate_all_chapters(
            topic=topic.strip(),
            project_type=project_type,
            academic_level=academic_level,
            word_count=word_count,
            instructions=instructions,
            selected_chapters=selected_chapters,
            source_context=source_context
        )

        chapters = split_chapters(
            report_text,
            selected_chapters
        )

        st.session_state["generated_chapters"] = chapters
        st.session_state["project_title"] = topic.strip()

        progress.progress(1.0)
        status.empty()

        if len(chapters) == 1 and "Complete Report" in chapters:
            st.warning(
                "Gemini returned the report without the expected chapter "
                "markers. The complete response is preserved below."
            )
        else:
            st.success(
                f"Report generated successfully: {len(chapters)} section(s)."
            )

    except Exception as exc:
        progress.empty()
        status.empty()

        message = str(exc)

        st.error("Gemini could not generate the report.")

        if "429" in message or "RESOURCE_EXHAUSTED" in message:
            st.warning(
                "The Gemini API quota or rate limit has been reached. "
                "Wait until the quota resets, or check your usage and "
                "limits in Google AI Studio."
            )
        elif "503" in message or "UNAVAILABLE" in message.upper():
            st.warning(
                "Gemini is temporarily overloaded. Please wait a few "
                "minutes and try again."
            )
        elif "403" in message or "PERMISSION_DENIED" in message:
            st.warning(
                "The API may be disabled for your Google Cloud project, "
                "or your key may not have permission to use it."
            )
        elif "404" in message or "NOT_FOUND" in message:
            st.warning(
                "The configured Gemini model is unavailable. Check "
                "GEMINI_MODEL in Streamlit Secrets and use a model "
                "available to your account."
            )
        else:
            st.warning(
                "Check your API key, model configuration, and the "
                "detailed error below."
            )

        with st.expander("Technical error details"):
            st.code(message[:4000])


# ==================================================
# 8. DISPLAY AND DOWNLOAD REPORT
# ==================================================

if st.session_state.get("generated_chapters"):
    chapters = st.session_state["generated_chapters"]
    title = st.session_state.get(
        "project_title",
        "Project Report"
    )

    st.divider()
    st.subheader("2. Generated project report")

    for index, (chapter, content) in enumerate(chapters.items()):
        with st.expander(chapter, expanded=False):
            st.markdown(content)

            filename = (
                re.sub(r"[^a-zA-Z0-9_-]+", "_", chapter).strip("_")
                or "chapter"
            )

            st.download_button(
                label=f"Download {chapter} (.txt)",
                data=content,
                file_name=f"{filename}.txt",
                mime="text/plain",
                key=f"chapter_download_{index}"
            )

    full_text = report_as_text(title, chapters)

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
            word_file = create_word_report(title, chapters)

            st.download_button(
                "📝 Download Word",
                data=word_file,
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
            pdf_file = create_pdf_report(title, chapters)

            st.download_button(
                "📕 Download PDF",
                data=pdf_file,
                file_name="project_report.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        except Exception as exc:
            st.error(f"PDF export failed: {exc}")

    st.caption(
        "Review the content and verify the original sources before "
        "submitting your report. AI-generated references and claims "
        "should be checked against the original publications."
    )
