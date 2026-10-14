
import streamlit as st
import requests
import pandas as pd
from openai import OpenAI, OpenAIError

st.set_page_config(
    page_title="AI Project Report Generator",
    page_icon="📚",
    layout="wide"
)

st.title("📚 AI Project Report Generator")
st.write(
    "Research your topic and generate detailed, "
    "source-aware project report chapters."
)

st.divider()
st.header("1. Configure Your Report")

topic = st.text_area(
    "Project topic",
    placeholder="Example: Impact of AI on the Indian Printing Industry",
    height=100
)

col1, col2 = st.columns(2)

with col1:
    pages = st.selectbox(
        "Target report length",
        [20, 21, 22, 23, 24, 25],
        index=5
    )

    report_type = st.selectbox(
        "Report type",
        [
            "Academic Project",
            "Technical Report",
            "Business Report",
            "Research Report",
            "General Report"
        ]
    )

with col2:
    language = st.selectbox(
        "Language",
        ["English", "Hindi", "Marathi"]
    )

    research_mode = st.selectbox(
        "Research preference",
        [
            "Search the web",
            "Academic and official sources first"
        ]
    )

include_images = st.checkbox("Plan relevant images", value=True)
include_graphs = st.checkbox("Plan graphs and statistics", value=True)
include_references = st.checkbox(
    "Include citations and references",
    value=True
)

st.divider()


def search_openalex(search_topic, max_results=10):
    """Search OpenAlex for academic publications."""

    response = requests.get(
        "https://api.openalex.org/works",
        params={
            "search": search_topic,
            "per-page": max_results,
            "sort": "relevance_score:desc"
        },
        timeout=30
    )

    response.raise_for_status()
    results = response.json().get("results", [])
    papers = []

    for work in results:
        authors = []

        for authorship in (work.get("authorships") or [])[:5]:
            author = authorship.get("author") or {}
            if author.get("display_name"):
                authors.append(author["display_name"])

        location = work.get("primary_location") or {}

        papers.append({
            "Title": work.get("title") or "Untitled",
            "Year": work.get("publication_year") or "Unknown",
            "Authors": ", ".join(authors) or "Not listed",
            "URL": location.get("landing_page_url")
                   or work.get("doi")
                   or "",
            "Abstract": decode_abstract(
                work.get("abstract_inverted_index")
            )
        })

    return papers


def decode_abstract(inverted_index):
    """Reconstruct an abstract supplied by OpenAlex."""

    if not inverted_index:
        return "Abstract not available in OpenAlex."

    words = {}

    for word, positions in inverted_index.items():
        for position in positions:
            words[position] = word

    return " ".join(words[i] for i in sorted(words))


def generate_chapter(
    client,
    topic,
    chapter,
    report_type,
    language,
    pages,
    papers
):
    """Generate one report chapter using the supplied research."""

    research_text = ""

    for number, paper in enumerate(papers[:10], start=1):
        research_text += (
            f"\nSource {number}\n"
            f"Title: {paper.get('Title', 'Unknown')}\n"
            f"Authors: {paper.get('Authors', 'Unknown')}\n"
            f"Year: {paper.get('Year', 'Unknown')}\n"
            f"URL: {paper.get('URL', '')}\n"
            f"Abstract: {paper.get('Abstract', '')}\n"
        )

    if not research_text:
        research_text = (
            "No research papers were supplied. "
            "Do not invent sources or claim research was verified."
        )

    prompt = f"""
You are an academic and technical report writing assistant.

PROJECT TOPIC: {topic}
REPORT TYPE: {report_type}
TARGET TOTAL REPORT LENGTH: {pages} pages
CHAPTER TO WRITE: {chapter}
OUTPUT LANGUAGE: {language}

RESEARCH PREFERENCE: Academic and official sources first.

RESEARCH MATERIAL:
{research_text}

WRITING INSTRUCTIONS:
1. Write a detailed, well-organized chapter with useful headings.
2. Use clear, formal language appropriate to the report type.
3. Explain concepts, evidence, practical implications and limitations.
4. Use supplied research material where relevant.
5. Never invent authors, titles, statistics, quotations, DOIs or URLs.
6. Do not claim to have read a complete paper when only its metadata
   or abstract is available.
7. Distinguish sourced findings from your own analysis.
8. Cite supplied sources by their source number, for example [Source 1],
   and include a reference list with available title, authors, year and URL.
9. If evidence is insufficient, explicitly state what needs verification.
10. Do not invent survey results or experimental findings.
11. Make this chapter substantial, but do not pad it with repetition.
12. Return the chapter in Markdown, with headings and bullet points
    where appropriate.
13. Do not write the other chapters of the report.

Optional visual planning:
Relevant images requested: {include_images}
Graphs/statistics requested: {include_graphs}
References requested: {include_references}

For requested visuals, suggest specific images or graphs that would
improve this chapter. Do not fabricate data. State what real dataset
would be needed for any graph that cannot be supported by the supplied
research.
"""

    response = client.responses.create(
        model=st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini"),
        input=prompt,
        max_output_tokens=5000
    )

    return response.output_text


def get_client():
    """Read the API key from Streamlit Secrets."""

    api_key = st.secrets.get("OPENAI_API_KEY", "")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is missing from Streamlit Secrets."
        )

    return OpenAI(api_key=api_key)


st.header("2. Find Research Papers")

if st.button("🔎 Search Research Sources", type="secondary"):
    if not topic.strip():
        st.warning("Enter a project topic first.")
    else:
        try:
            with st.spinner("Searching academic publications..."):
                papers = search_openalex(topic.strip())

            st.session_state["research_papers"] = papers
            st.session_state["research_topic"] = topic.strip()

            if papers:
                st.success(f"Found {len(papers)} publications.")
            else:
                st.info("No publications found. Try a broader topic.")

      
        except requests.RequestException as error:
            st.error(
                f"Research request failed: {type(error).__name__}"
            )

            if isinstance(error, requests.HTTPError):
                response = error.response

                if response is not None:
                    st.error(
                        f"OpenAlex HTTP status: {response.status_code}"
                    )

            elif isinstance(error, requests.Timeout):
                st.warning(
                    "The request timed out. Please try again."
                )

            elif isinstance(error, requests.ConnectionError):
                st.warning(
                    "Could not connect to OpenAlex. "
                    "Check your connection or try again later."
                )


papers = st.session_state.get("research_papers", [])

if papers:
    st.dataframe(
        pd.DataFrame([
            {key: value for key, value in paper.items()
             if key != "Abstract"}
            for paper in papers
        ]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("Source link")
        }
    )

    st.download_button(
        "Download research results (CSV)",
        data=pd.DataFrame([
            {key: value for key, value in paper.items()
             if key != "Abstract"}
            for paper in papers
        ]).to_csv(index=False),
        file_name="research_results.csv",
        mime="text/csv"
    )

st.divider()
st.header("3. Generate Your First AI Chapter")

chapter = st.selectbox(
    "Choose a chapter",
    [
        "Abstract and Executive Summary",
        "Chapter 1: Introduction",
        "Chapter 2: Literature Review",
        "Chapter 3: Research Methodology",
        "Chapter 4: Main Analysis and Discussion",
        "Chapter 5: Findings and Recommendations",
        "Chapter 6: Conclusion"
    ]
)

st.caption(
    "Search for research papers first so the AI can use the "
    "available source metadata and abstracts."
)

if st.button("✍️ Generate AI Chapter", type="primary"):
    if not topic.strip():
        st.warning("Enter a project topic first.")

    elif not papers:
        st.warning(
            "Search for research papers first, then generate a chapter."
        )

    elif st.session_state.get("research_topic") != topic.strip():
        st.warning(
            "Your topic has changed. Search for research papers again."
        )

    else:
        try:
            client = get_client()

            with st.spinner(
                "Writing your chapter. This may take a minute..."
            ):
                chapter_text = generate_chapter(
                    client=client,
                    topic=topic.strip(),
                    chapter=chapter,
                    report_type=report_type,
                    language=language,
                    pages=pages,
                    papers=papers
                )

            st.session_state["generated_chapter"] = chapter_text
            st.session_state["generated_chapter_title"] = chapter

            st.success("Chapter generated successfully!")

        except ValueError as error:
            st.error(str(error))

        except OpenAIError as error:
            st.error(
                "The AI service returned an error. Check your API "
                "account, billing, model access and usage limits. "
                "Try again after resolving the issue."
            )

        except Exception as error:
            st.error(
                f"Unexpected error: {type(error).__name__}. "
                "Check the app logs for details."
            )

if st.session_state.get("generated_chapter"):
    st.divider()
    st.subheader(
        st.session_state.get(
            "generated_chapter_title", "Generated Chapter"
        )
    )

    chapter_text = st.session_state["generated_chapter"]

    st.markdown(chapter_text)

    st.download_button(
        "⬇️ Download Chapter as Markdown",
        data=chapter_text,
        file_name="project_report_chapter.md",
        mime="text/markdown"
    )

st.caption(
    "Personal AI Project Report Generator | "
    "Verify sources and factual claims before using the report."
)
