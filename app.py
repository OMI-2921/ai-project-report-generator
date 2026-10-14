
import os
import re
import time
import html
import textwrap
from io import BytesIO
from xml.sax.saxutils import escape

import requests
import streamlit as st
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from google import genai
from docx import Document
from docx.shared import Inches as DocxInches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Image as PDFImage, Table, TableStyle, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from reportlab.lib import colors


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
    "Generate structured student project reports with academic "
    "sources, diagrams, charts, and downloadable Word and PDF files."
)


# ==================================================
# 2. SETTINGS
# ==================================================

def get_setting(name, default=""):
    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value else default
    except Exception:
        return os.getenv(name, default)


GEMINI_API_KEY = get_setting("GEMINI_API_KEY")
GEMINI_MODEL = get_setting("GEMINI_MODEL", "gemini-3.5-flash-lite")

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

HEADERS = {
    "User-Agent": "AIProjectReportGenerator/2.0"
}


# ==================================================
# 3. ACADEMIC SOURCE SEARCH
# ==================================================

def decode_abstract(inverted_index):
    if not inverted_index:
        return ""

    words = {}
    for word, positions in inverted_index.items():
        for position in positions:
            words[position] = word

    return " ".join(words[position] for position in sorted(words))


def search_openalex(topic, limit):
    try:
        response = requests.get(
            "https://api.openalex.org/works",
            params={
                "search": topic,
                "per-page": limit,
                "select": (
                    "id,doi,title,publication_year,authorships,"
                    "abstract_inverted_index,primary_location"
                )
            },
            headers=HEADERS,
            timeout=25
        )
        response.raise_for_status()

        results = []
        for item in response.json().get("results", []):
            authors = []
            for authorship in item.get("authorships", [])[:10]:
                name = (authorship.get("author") or {}).get("display_name")
                if name:
                    authors.append(name)

            location = item.get("primary_location") or {}
            source = location.get("source") or {}
            doi = item.get("doi") or ""

            results.append({
                "title": item.get("title") or "Untitled",
                "year": item.get("publication_year") or "Unknown",
                "authors": authors,
                "journal": source.get("display_name", ""),
                "doi": doi,
                "url": doi or item.get("id", ""),
                "abstract": decode_abstract(
                    item.get("abstract_inverted_index")
                ),
                "source_provider": "OpenAlex"
            })

        return results

    except requests.RequestException:
        return []


def search_crossref(topic, limit):
    try:
        response = requests.get(
            "https://api.crossref.org/works",
            params={"query": topic, "rows": limit},
            headers=HEADERS,
            timeout=25
        )
        response.raise_for_status()

        results = []
        items = response.json().get("message", {}).get("items", [])

        for item in items:
            title_list = item.get("title") or []
            title = title_list[0] if title_list else "Untitled"

            authors = []
            for author in item.get("author", [])[:10]:
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
                or item.get("published-print", {}).get("date-parts")
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
                "authors": authors,
                "journal": (
                    (item.get("container-title") or [""])[0]
                ),
                "doi": doi,
                "url": (
                    f"https://doi.org/{doi}"
                    if doi else item.get("URL", "")
                ),
                "abstract": abstract,
                "source_provider": "Crossref"
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


def usable_sources(papers):
    """Prefer sources with identifiable titles and author metadata."""
    cleaned = []
    seen = set()

    for paper in papers:
        title = (paper.get("title") or "").strip()
        url = (paper.get("url") or "").strip()

        if not title or title == "Untitled":
            continue

        key = (title.lower(), url.lower())
        if key in seen:
            continue
        seen.add(key)

        cleaned.append(paper)

    return cleaned


def format_authors(authors):
    if not authors:
        return "Author metadata unavailable"

    if len(authors) == 1:
        return authors[0]

    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"

    return ", ".join(authors[:-1]) + ", and " + authors[-1]


def format_reference(paper):
    authors = format_authors(paper.get("authors", []))
    year = paper.get("year", "Unknown")
    title = paper.get("title", "Untitled")
    journal = paper.get("journal", "")
    url = paper.get("url", "")

    parts = [f"{authors} ({year}). {title}."]

    if journal:
        parts.append(f"{journal}.")

    if url:
        parts.append(url)

    return " ".join(parts)


def build_source_context(papers):
    blocks = []

    for i, paper in enumerate(papers, start=1):
        blocks.append(
            f"SOURCE {i}\n"
            f"Title: {paper['title']}\n"
            f"Authors: {format_authors(paper.get('authors', []))}\n"
            f"Year: {paper.get('year', 'Unknown')}\n"
            f"Journal: {paper.get('journal', '')}\n"
            f"DOI or URL: {paper.get('url', '')}\n"
            f"Abstract: {(paper.get('abstract') or 'Not available')[:1000]}\n"
        )

    return "\n".join(blocks)


# ==================================================
# 4. REPORT GENERATION
# ==================================================

DEFAULT_CHAPTERS = [
    "Abstract",
    "Introduction",
    "Problem Statement",
    "Objectives",
    "Scope of the Project",
    "Literature Review",
    "Proposed Methodology",
    "System Design",
    "Implementation",
    "Testing and Evaluation",
    "Results and Discussion",
    "Limitations",
    "Future Scope",
    "Conclusion",
    "References"
]


def generate_report(
    topic,
    project_type,
    academic_level,
    word_count,
    instructions,
    chapters,
    source_context,
    project_details
):
    chapter_list = "\n".join(f"- {chapter}" for chapter in chapters)

    prompt = f"""
You are an academic project-report writing assistant.

PROJECT TOPIC: {topic}
PROJECT TYPE: {project_type}
ACADEMIC LEVEL: {academic_level}
TARGET WORDS PER CHAPTER: approximately {word_count}

STUDENT-PROVIDED PROJECT DETAILS:
{project_details or "No implementation details supplied."}

ADDITIONAL INSTRUCTIONS:
{instructions or "None"}

REQUESTED CHAPTERS, IN THIS ORDER:
{chapter_list}

ACADEMIC SOURCES RETRIEVED FROM OPENALEX OR CROSSREF:
{source_context or "No academic sources retrieved."}

Write a substantial, well-organized project report in formal academic
English. Use meaningful headings and subheadings.

Separate every requested chapter with the exact marker:
<<<CHAPTER: Chapter Name>>>

Repeat the marker for every requested chapter, preserving the exact names
and order supplied above.

ACADEMIC INTEGRITY:
- Do not invent experiments, results, sample sizes, performance scores,
  survey responses, authors, or publication details.
- If the project has not been implemented, clearly describe implementation
  as proposed or planned rather than completed.
- In Results and Discussion, if no real results or dataset are provided,
  state that empirical results are not yet available. Explain what should
  be measured instead of inventing numerical results.
- Cite sources in the text using author and year only when the source
  metadata supports that citation.
- Never invent a citation to support a statement.
- In References, list only supplied sources that are relevant to the topic.
  Do not use "Authors not listed" as an author name. If author metadata is
  unavailable, clearly label it "Author metadata unavailable".
- Do not claim a source proves something if its abstract or contents do
  not support that claim.
- Avoid repeating identical paragraphs across chapters.
- Adapt the report to the selected project type.
- For software projects, explain modules, architecture, inputs, outputs,
  and testing plans.
- For data projects, explain data sources, preprocessing, methods, metrics,
  and evaluation requirements.
- For business projects, include the relevant business framework and
  evaluation approach.
- For engineering projects, explain components, design considerations,
  and validation requirements.
- Do not pretend that a diagram or chart has been included; describe its
  purpose in the report text if relevant.
- Return only the report with chapter markers.
"""

    last_error = None

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )

            result = response.text
            if result and result.strip():
                return result.strip()

            raise ValueError("Gemini returned an empty response.")

        except Exception as exc:
            last_error = exc
            message = str(exc).lower()

            if (
                ("503" in message or "unavailable" in message)
                and attempt < 2
            ):
                time.sleep(5 * (attempt + 1))
                continue

            raise

    raise last_error


def split_chapters(report_text, requested_chapters):
    pattern = r"<<<CHAPTER:\s*(.*?)\s*>>>"
    matches = list(re.finditer(pattern, report_text, re.IGNORECASE))

    if not matches:
        return {"Complete Report": report_text.strip()}

    result = {}

    for i, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report_text)
        content = report_text[start:end].strip()

        canonical = next(
            (c for c in requested_chapters if c.lower() == name.lower()),
            name
        )

        if content:
            result[canonical] = content

    return result or {"Complete Report": report_text.strip()}


# ==================================================
# 5. AUTOMATIC DIAGRAMS AND CHARTS
# ==================================================

def make_workflow_diagram(topic, project_type):
    """Create a generic workflow diagram, not a claim about completed work."""
    fig, ax = plt.subplots(figsize=(10, 2.8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis("off")

    labels = [
        "Problem\nDefinition",
        "Requirements /\nData Collection",
        "Design /\nMethod",
        "Implementation /\nAnalysis",
        "Testing /\nEvaluation"
    ]

    xs = [1, 3, 5, 7, 9]

    for i, (x, label) in enumerate(zip(xs, labels)):
        ax.text(
            x, 1.5, label,
            ha="center", va="center", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.5", fill=False)
        )

        if i < len(xs) - 1:
            ax.annotate(
                "", xy=(xs[i + 1] - 0.65, 1.5),
                xytext=(x + 0.65, 1.5),
                arrowprops=dict(arrowstyle="->", linewidth=1.2)
            )

    ax.set_title(f"Proposed Workflow: {topic[:70]}", fontsize=11)
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def make_architecture_diagram(topic, project_type):
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8)
    ax.axis("off")

    boxes = [
        (5, 6.7, "User / Stakeholder"),
        (5, 5.1, "Input and Presentation Layer"),
        (5, 3.5, "Core Processing / Business Logic"),
        (5, 1.9, "Data Storage / External Services")
    ]

    for x, y, label in boxes:
        ax.text(
            x, y, label,
            ha="center", va="center", fontsize=10,
            bbox=dict(boxstyle="round,pad=0.65", fill=False)
        )

    for y1, y2 in [(6.3, 5.5), (4.7, 3.9), (3.1, 2.3)]:
        ax.annotate(
            "", xy=(5, y2), xytext=(5, y1),
            arrowprops=dict(arrowstyle="<->", linewidth=1.2)
        )

    ax.set_title(f"Illustrative System Architecture: {topic[:60]}", fontsize=11)
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def make_project_plan_chart():
    """An explicitly illustrative project schedule, not measured results."""
    tasks = [
        "Requirements",
        "Research",
        "Design",
        "Development",
        "Testing",
        "Documentation"
    ]
    starts = [0, 1, 2, 3, 5, 5]
    durations = [1, 2, 1, 2, 1, 2]

    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.barh(tasks, durations, left=starts)
    ax.set_xlabel("Illustrative project week")
    ax.set_title("Example Project Timeline (Adjust to Your Actual Plan)")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def build_visuals(topic, project_type):
    return {
        "Workflow Diagram": make_workflow_diagram(topic, project_type),
        "System Architecture Diagram": make_architecture_diagram(
            topic, project_type
        ),
        "Illustrative Project Timeline": make_project_plan_chart()
    }


# ==================================================
# 6. DOCUMENT FORMATTING
# ==================================================

def clean_paragraph(text):
    text = text.strip()
    text = re.sub(r"^\s*#{1,6}\s*", "", text)
    text = re.sub(r"^\s*[-*]\s+", "• ", text)
    return text


def report_as_text(title, chapters, references, include_visuals=True):
    parts = [
        title,
        "=" * len(title),
        "",
        "Note: Review this draft, confirm project-specific details, "
        "and verify citations before submission.",
        ""
    ]

    for chapter, content in chapters.items():
        parts.extend([
            "",
            chapter.upper(),
            "-" * len(chapter),
            content
        ])

        if chapter == "System Design" and include_visuals:
            parts.append(
                "[Generated workflow and architecture diagrams are included "
                "in the Word and PDF versions.]"
            )

    if references and "References" not in chapters:
        parts.extend(["", "REFERENCES", "----------"])
        parts.extend(references)

    return "\n".join(parts)


def create_word_report(title, chapters, references, visuals):
    doc = Document()

    section = doc.sections[0]
    section.top_margin = DocxInches(0.75)
    section.bottom_margin = DocxInches(0.75)
    section.left_margin = DocxInches(0.85)
    section.right_margin = DocxInches(0.85)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)

    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(title)
    title_run.bold = True
    title_run.font.size = Pt(22)

    doc.add_paragraph("")
    note = doc.add_paragraph(
        "Student project report draft — verify project details and sources."
    )
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_page_break()

    doc.add_heading("Table of Contents", level=1)
    for chapter in chapters:
        doc.add_paragraph(chapter, style="List Number")
    doc.add_page_break()

    for chapter, content in chapters.items():
        doc.add_heading(chapter, level=1)

        for raw in content.splitlines():
            line = clean_paragraph(raw)
            if not line:
                continue

            if line.startswith("• "):
                doc.add_paragraph(line[2:], style="List Bullet")
            elif (
                len(line) < 100
                and line.endswith(":")
            ):
                doc.add_heading(line.rstrip(":"), level=2)
            else:
                doc.add_paragraph(line)

        if chapter == "Proposed Methodology":
            doc.add_heading("Proposed Workflow Diagram", level=2)
            doc.add_picture(
                BytesIO(visuals["Workflow Diagram"]),
                width=DocxInches(6.0)
            )
            doc.add_paragraph(
                "Figure 1. Illustrative workflow for the proposed project."
            )

        if chapter == "System Design":
            doc.add_heading("Illustrative System Architecture", level=2)
            doc.add_picture(
                BytesIO(visuals["System Architecture Diagram"]),
                width=DocxInches(5.5)
            )
            doc.add_paragraph(
                "Figure 2. Generic architecture; adapt to the actual system."
            )

        if chapter in ("Implementation", "Testing and Evaluation"):
            doc.add_heading("Illustrative Project Schedule", level=2)
            doc.add_picture(
                BytesIO(visuals["Illustrative Project Timeline"]),
                width=DocxInches(5.8)
            )
            doc.add_paragraph(
                "Figure 3. Example schedule only; replace with the actual plan."
            )

    if references and "References" not in chapters:
        doc.add_heading("References", level=1)
        for ref in references:
            doc.add_paragraph(ref, style="List Number")

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Times-Roman", 9)
    canvas.drawCentredString(
        A4[0] / 2, 0.35 * inch, f"Page {doc.page}"
    )
    canvas.restoreState()


def create_pdf_report(title, chapters, references, visuals):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.65 * inch
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontName="Times-Bold",
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        spaceAfter=24
    ))
    styles.add(ParagraphStyle(
        name="ReportBody",
        parent=styles["BodyText"],
        fontName="Times-Roman",
        fontSize=10.5,
        leading=15,
        spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="FigureCaption",
        parent=styles["BodyText"],
        fontSize=9,
        alignment=TA_CENTER,
        spaceAfter=12
    ))

    story = [
        Spacer(1, 1.4 * inch),
        Paragraph(escape(title), styles["ReportTitle"]),
        Spacer(1, 0.2 * inch),
        Paragraph(
            "Student project report draft",
            styles["Heading2"]
        ),
        Spacer(1, 0.3 * inch),
        Paragraph(
            "Review project-specific details and verify all references "
            "before submission.",
            styles["ReportBody"]
        ),
        PageBreak(),
        Paragraph("Table of Contents", styles["Heading1"])
    ]

    for chapter in chapters:
        story.append(Paragraph(escape(chapter), styles["ReportBody"]))

    story.append(PageBreak())

    for chapter, content in chapters.items():
        story.append(Paragraph(escape(chapter), styles["Heading1"]))
        story.append(Spacer(1, 8))

        for raw in content.splitlines():
            line = clean_paragraph(raw)
            if not line:
                continue

            story.append(
                Paragraph(
                    escape(line).replace("\n", "<br/>"),
                    styles["ReportBody"]
                )
            )

        if chapter == "Proposed Methodology":
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                "Proposed Workflow Diagram",
                styles["Heading2"]
            ))
            story.append(PDFImage(
                BytesIO(visuals["Workflow Diagram"]),
                width=6.3 * inch,
                height=1.8 * inch
            ))
            story.append(Paragraph(
                "Figure 1. Illustrative workflow; adapt to the actual project.",
                styles["FigureCaption"]
            ))

        if chapter == "System Design":
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                "Illustrative System Architecture",
                styles["Heading2"]
            ))
            story.append(PDFImage(
                BytesIO(visuals["System Architecture Diagram"]),
                width=5.5 * inch,
                height=2.8 * inch
            ))
            story.append(Paragraph(
                "Figure 2. Generic architecture; adapt to the actual system.",
                styles["FigureCaption"]
            ))

        if chapter in ("Implementation", "Testing and Evaluation"):
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                "Illustrative Project Schedule",
                styles["Heading2"]
            ))
            story.append(PDFImage(
                BytesIO(visuals["Illustrative Project Timeline"]),
                width=5.8 * inch,
                height=2.7 * inch
            ))
            story.append(Paragraph(
                "Figure 3. Example schedule only; replace with the actual plan.",
                styles["FigureCaption"]
            ))

        story.append(Spacer(1, 12))

    if references and "References" not in chapters:
        story.append(Paragraph("References", styles["Heading1"]))
        for ref in references:
            story.append(Paragraph(
                escape(ref), styles["ReportBody"]
            ))

    doc.build(
        story,
        onFirstPage=add_page_number,
        onLaterPages=add_page_number
    )
    buffer.seek(0)
    return buffer.getvalue()


# ==================================================
# 7. PROJECT INPUTS
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
            3, 10, 5
        )

        word_count = st.selectbox(
            "Approximate words per chapter",
            [200, 300, 500, 700],
            index=2
        )

    project_details = st.text_area(
        "Project details (important for accurate reports)",
        placeholder=(
            "Describe the actual system, tools, dataset, modules, "
            "implementation status, test results, or methodology. "
            "Leave unknown results blank rather than guessing."
        ),
        height=130
    )

    instructions = st.text_area(
        "Additional instructions",
        placeholder=(
            "College format, required chapters, technologies, "
            "citation style, or supervisor instructions."
        )
    )

    selected_chapters = st.multiselect(
        "Select report chapters",
        DEFAULT_CHAPTERS,
        default=[
            "Abstract",
            "Introduction",
            "Problem Statement",
            "Objectives",
            "Literature Review",
            "Proposed Methodology",
            "System Design",
            "Implementation",
            "Testing and Evaluation",
            "Results and Discussion",
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
# 8. GENERATE REPORT
# ==================================================

if submitted:
    if not topic.strip():
        st.error("Please enter your project topic.")
        st.stop()

    if not selected_chapters:
        st.error("Select at least one chapter.")
        st.stop()

    st.session_state.pop("generated_chapters", None)
    st.session_state.pop("project_title", None)
    st.session_state.pop("project_visuals", None)
    st.session_state.pop("project_references", None)

    with st.spinner("Searching academic sources..."):
        papers, provider = search_research(topic.strip(), research_count)
        papers = usable_sources(papers)

    if papers:
        st.success(f"Retrieved {len(papers)} source records from {provider}.")
    else:
        st.warning(
            "No research sources could be retrieved. You can still generate "
            "a report, but its literature review and references will be limited."
        )

    with st.expander("Review retrieved academic sources"):
        if not papers:
            st.write("No source records available.")
        for index, paper in enumerate(papers, start=1):
            st.markdown(f"**{index}. {paper['title']}**")
            st.write(f"Authors: {format_authors(paper.get('authors', []))}")
            st.write(f"Year: {paper.get('year', 'Unknown')}")
            if paper.get("url"):
                st.write(paper["url"])

    source_context = build_source_context(papers)
    progress = st.progress(0)
    status = st.empty()

    try:
        status.info("Generating report chapters with Gemini...")
        report_text = generate_report(
            topic=topic.strip(),
            project_type=project_type,
            academic_level=academic_level,
            word_count=word_count,
            instructions=instructions,
            chapters=selected_chapters,
            source_context=source_context,
            project_details=project_details
        )
        progress.progress(0.7)

        chapters = split_chapters(report_text, selected_chapters)

        status.info("Creating diagrams and charts...")
        visuals = build_visuals(topic.strip(), project_type)
        references = [format_reference(p) for p in papers]
        progress.progress(1.0)

        st.session_state["generated_chapters"] = chapters
        st.session_state["project_title"] = topic.strip()
        st.session_state["project_visuals"] = visuals
        st.session_state["project_references"] = references

        status.empty()
        st.success("Report generated. Review it before downloading.")

    except Exception as exc:
        progress.empty()
        status.empty()
        message = str(exc)
        st.error("The report could not be generated.")

        if "429" in message or "RESOURCE_EXHAUSTED" in message:
            st.warning(
                "Gemini quota or rate limit reached. Wait for the quota "
                "to reset, or check Google AI Studio usage and limits."
            )
        elif "503" in message or "UNAVAILABLE" in message.upper():
            st.warning(
                "Gemini is temporarily overloaded. Wait a few minutes "
                "and try again."
            )
        elif "403" in message or "PERMISSION_DENIED" in message:
            st.warning("Check API access and Google Cloud API settings.")
        elif "404" in message or "NOT_FOUND" in message:
            st.warning(
                "The configured Gemini model may not be available to your "
                "account. Check GEMINI_MODEL in Streamlit Secrets."
            )
        else:
            st.warning("Check the API key, model configuration, and error below.")

        with st.expander("Technical error details"):
            st.code(message[:4000])


# ==================================================
# 9. PREVIEW AND DOWNLOAD
# ==================================================

if st.session_state.get("generated_chapters"):
    chapters = st.session_state["generated_chapters"]
    title = st.session_state.get("project_title", "Project Report")
    visuals = st.session_state.get("project_visuals", {})
    references = st.session_state.get("project_references", [])

    st.divider()
    st.subheader("2. Report preview")

    for index, (chapter, content) in enumerate(chapters.items()):
        with st.expander(chapter, expanded=False):
            st.markdown(content)
            st.download_button(
                f"Download {chapter} (.txt)",
                data=content,
                file_name=(
                    re.sub(r"[^a-zA-Z0-9_-]+", "_", chapter).strip("_")
                    or "chapter"
                ) + ".txt",
                mime="text/plain",
                key=f"chapter_download_{index}"
            )

    st.subheader("3. Generated visuals")
    for name, image_bytes in visuals.items():
        with st.expander(name):
            st.image(image_bytes, caption=name, use_container_width=True)

    st.divider()
    st.subheader("4. Download complete report")

    full_text = report_as_text(title, chapters, references)

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
            word_file = create_word_report(
                title, chapters, references, visuals
            )
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
            pdf_file = create_pdf_report(
                title, chapters, references, visuals
            )
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
        "The diagrams and timeline are illustrative templates, not proof of "
        "completed implementation or measured results. Verify sources, replace "
        "generic diagrams with your actual design, and follow your institution's "
        "reporting and AI-use requirements."
    )
