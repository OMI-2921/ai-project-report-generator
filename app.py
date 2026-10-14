
import streamlit as st

st.set_page_config(
    page_title="AI Project Report Generator",
    page_icon="📚",
    layout="wide"
)

st.title("📚 AI Project Report Generator")

st.write(
    "Generate detailed project reports with research, "
    "images, graphs, references, and downloadable files."
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

include_images = st.checkbox(
    "Include relevant images",
    value=True
)

include_graphs = st.checkbox(
    "Include graphs and statistics",
    value=True
)

include_references = st.checkbox(
    "Include citations and bibliography",
    value=True
)

st.divider()

if st.button("🚀 Generate Project Report", type="primary"):
    if not topic.strip():
        st.warning("Please enter a project topic first.")
    else:
        st.info(
            "Your report settings are ready! "
            "The research and report generation engine "
            "will be connected in the next development stages."
        )

st.caption(
    "Personal AI Report Generator | Built with Python and Streamlit"
)
