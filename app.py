
import streamlit as st
import requests

st.set_page_config(
    page_title="AI Project Report Generator",
    page_icon="📚",
    layout="wide"
)

st.title("📚 AI Project Report Generator")
st.write(
    "Research topics and prepare detailed project reports "
    "with sources, images, graphs and references."
)

st.divider()
st.header("Create a New Report")

topic = st.text_area(
    "Enter your project topic",
    placeholder="Example: Impact of AI on the Indian Printing Industry",
    height=120
)

col1, col2 = st.columns(2)

with col1:
    pages = st.selectbox(
        "Report length",
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
        "Report language",
        ["English", "Hindi", "Marathi"]
    )
    research_mode = st.selectbox(
        "Research preference",
        [
            "Search the web",
            "Academic and official sources first"
        ]
    )

include_images = st.checkbox("Include relevant images", True)
include_graphs = st.checkbox("Include graphs and statistics", True)
include_references = st.checkbox("Include citations and bibliography", True)

st.divider()


def search_openalex(search_topic, max_results=10):
    """Find academic publications related to a topic."""

    url = "https://api.openalex.org/works"

    params = {
        "search": search_topic,
        "per-page": max_results,
        "sort": "relevance_score:desc"
    }

    response = requests.get(
        url,
        params=params,
        timeout=30
    )
    response.raise_for_status()

    data = response.json()
    papers = []

    for work in data.get("results", []):
        title = work.get("title") or "Untitled"
        publication_year = work.get("publication_year")
        doi = work.get("doi")
        landing_page = work.get("primary_location") or {}
        source = landing_page.get("landing_page_url")
        authorships = work.get("authorships") or []

        authors = []
        for authorship in authorships[:5]:
            author = authorship.get("author") or {}
            name = author.get("display_name")
            if name:
                authors.append(name)

        papers.append({
            "Title": title,
            "Year": publication_year or "Unknown",
            "Authors": ", ".join(authors) or "Not listed",
            "DOI": doi or "Not listed",
            "URL": source or doi or "No direct link available"
        })

    return papers


if st.button("🔎 Search Research Sources", type="primary"):
    if not topic.strip():
        st.warning("Please enter a project topic first.")
    else:
        try:
            with st.spinner("Searching academic publications..."):
                papers = search_openalex(topic.strip())

            if papers:
                st.session_state["research_papers"] = papers
                st.session_state["research_topic"] = topic.strip()
                st.success(f"Found {len(papers)} relevant publications.")
            else:
                st.session_state["research_papers"] = []
                st.info("No publications were found. Try a different topic.")

        except requests.RequestException as error:
            st.error(
                "The research service could not be reached. "
                "Please try again later."
            )

if "research_papers" in st.session_state:
    st.subheader("Research Results")
    st.caption(
        f"Search topic: {st.session_state.get('research_topic', '')}"
    )

    papers = st.session_state["research_papers"]

    if papers:
        st.dataframe(
            papers,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("Source link"),
                "DOI": st.column_config.LinkColumn("DOI")
            }
        )

        csv_data = __import__("pandas").DataFrame(papers).to_csv(
            index=False
        )

        st.download_button(
            "Download Research Results (CSV)",
            data=csv_data,
            file_name="research_results.csv",
            mime="text/csv"
        )

st.caption(
    "Research results are academic discovery results, "
    "not a complete or verified bibliography."
)
