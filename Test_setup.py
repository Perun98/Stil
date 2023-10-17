import os
import sys
import io
import pinecone
import streamlit as st
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores.pinecone import Pinecone
from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain.chains.query_constructor.base import AttributeInfo
from langchain.retrievers import PineconeHybridSearchRetriever
from pinecone_text.sparse import BM25Encoder
from langchain.agents.agent_types import AgentType
from langchain.agents import create_csv_agent
from langchain.agents import Tool, AgentType, initialize_agent
from langchain.chat_models import ChatOpenAI
from langchain.utilities import GoogleSerperAPIWrapper
from langchain.memory import ConversationBufferWindowMemory
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

from myfunc.mojafunkcija import (
    st_style,
    positive_login,
    StreamHandler,
    StreamlitRedirect,
    init_cond_llm,
    open_file,
)

st.set_page_config(page_title="Multi Tool Chatbot", page_icon="👉", layout="wide")

st_style()
version = "17.10.23. - Svi search Agent i memorija"
with st.sidebar:
    st.markdown(
        f"<p style='font-size: 10px; color: grey;'>{version}</p>",
        unsafe_allow_html=True,
    )


def set_namespace():
    with col1:
        st.session_state.name_semantic = st.selectbox(
            "Namespace za Semantic Search",
            (
                "positive",
                "pravnikprazan",
                "pravnikprefix",
                "pravnikschema",
                "pravnikfull",
                "bisprazan",
                "bisprefix",
                "bisschema",
                "bisfull",
                "koder",
            ),
            help="Pitanja o Positive uopstena",
        )
    with col2:
        st.session_state.name_self = st.selectbox(
            "Namespace za SelfQuery Search",
            ("sistematizacija3",),
            help="Pitanja o meta poljima",
        )
    with col3:
        st.session_state.name_hybrid = st.selectbox(
            "Namespace za Hybrid Search",
            (
                "pravnikkraciprazan",
                "pravnikkraciprefix",
                "pravnikkracischema",
                "pravnikkracifull",
                "bishybridprazan",
                "bishybridprefix",
                "bishybridschema",
                "bishybridfull",
                "pravnikprazan",
                "pravnikprefix",
                "pravnikschema",
                "pravnikfull",
                "bisprazan",
                "bisprefix",
                "bisschema",
                "bisfull",
            ),
            help="Pitanja o opisu radnih mesta",
        )


if "name_semantic" not in st.session_state:
    st.session_state.name_semantic = "positive"
if "name_self" not in st.session_state:
    st.session_state.name_self = "sistematizacija3"
if "name_hybrid" not in st.session_state:
    st.session_state.name_hybrid = "pravnikkraciprazan"
if "broj_k" not in st.session_state:
    st.session_state.broj_k = 3
if "alpha" not in st.session_state:
    st.session_state.alpha = None

if "uploaded_file" not in st.session_state:
    st.session_state.uploaded_file = "bnreport.csv"
if "direct_semantic" not in st.session_state:
    st.session_state.direct_semantic = None
if "direct_hybrid" not in st.session_state:
    st.session_state.direct_hybrid = None
if "direct_self" not in st.session_state:
    st.session_state.direct_self = None
if "direct_csv" not in st.session_state:
    st.session_state.direct_csv = None
if "input_prompt" not in st.session_state:
    st.session_state.input_prompt = None


st.subheader("Multi Tool Chatbot")
with st.expander("Pročitajte uputstvo 🧜‍♂️"):
    st.caption(
        """
                Na ovom mestu podesavate parametre sistema za testiranje. Za rad CSV agenta potrebno je da uploadujete csv fajl sa struktuiranim podacima.
                Za rad ostalih agenata potrebno je da odlucit eda li cete korisiti originalni prompt ili upit koji formira agent. Takodje, odaberite namespace za svaki metod.
                Izborom izlaza odlucujete da li ce se odgovor vratiti direktno iz alata ili ce se korisiti dodatni LLM za formiranje odgovora.
                Za hybrid search odredite koeficijent alpha koji odredjuje koliko ce biti zastupljena pretraga po kljucnim recima, a koliko po semantickom znacenju.
                Mozete odabrati i broj dokumenata koji se vracaju iz indeksa.
                Testiramo rad BIS i Pravnik sa upotrebom agenta. Na setup stranici mozete postaviti parametre za rad.
                Trenutno podesavanje tipa agenta, prompta agenta i opisi alata nisu podesivi iz korisnickog interfejsa.
                Trenutno nije u upotrebi Score limit za semantic search, koji vraca odgovor uvek ako je prozvan.
                Ovo su parametri koji ce se testirati u sledecim iteracijama.
                    """
    )
col1, col2, col3, col4, col5 = st.columns(5)
set_namespace()
with col1:
    st.session_state.direct_semantic = st.radio(
        "Direktan odgovor - Semantic",
        [True, False],
        key="semantic_key",
        horizontal=True,
        help="Pitanja o Positive uopstena",
    )
with col3:
    st.session_state.direct_hybrid = st.radio(
        "Direktan odgovor - Hybrid search",
        [True, False],
        horizontal=True,
        help="Pitanja o opisu radnih mesta",
    )
with col2:
    st.session_state.direct_self = st.radio(
        "Direktan odgovor - Self search",
        [True, False],
        horizontal=True,
        help="Pitanja o meta poljima",
    )

with col5:
    st.session_state.alpha = st.slider(
        "Hybrid keyword/semantic",
        0.0,
        1.0,
        0.5,
        0.1,
        help="Koeficijent koji određuje koliko će biti zastupljena pretraga po ključnim rečima, a koliko po semantičkom značenju. 0-0.4 pretezno Kljucne reci , 0.5 podjednako, 0.6-1 pretezno semanticko znacenje",
    )
    st.session_state.input_prompt = st.radio(
        "Originalni prompt?",
        [True, False],
        key="input_prompt_key",
        horizontal=True,
        help="Ako je odgovor False, onda se koristi upit koji formira Agent",
    )
with col4:
    st.session_state.broj_k = st.number_input(
        "Broj dokumenata - svi indexi",
        min_value=1,
        max_value=5,
        value=3,
        step=1,
        key="broj_k_key",
        help="Broj dokumenata koji se vraćaju iz indeksa",
    )

    st.session_state.direct_csv = st.radio(
        "Direktan odgovor - CSV search",
        [True, False],
        help="Pitanja o struktuiranim podacima",
        horizontal=True,
    )


def read_csv(upit):
    agent = create_csv_agent(
        ChatOpenAI(temperature=0),
        st.session_state.uploaded_file.name,
        verbose=True,
        agent_type=AgentType.OPENAI_FUNCTIONS,
        handle_parsing_errors=True,
    )
    # za prosledjivanje originalnog prompta alatu alternativa je upit
    if st.session_state.input_prompt == True:
        odgovor = agent.run(st.session_state.fix_prompt)
    else:
        odgovor = agent.run(upit)
    return str(odgovor)


# semantic search - klasini model
def rag(upit):
    # Initialize Pinecone
    pinecone.init(
        api_key=os.environ["PINECONE_API_KEY"],
        environment=os.environ["PINECONE_API_ENV"],
    )
    index_name = "embedings1"

    index = pinecone.Index(index_name)
    # vectorstore = Pinecone(
    #     index=index, embedding=OpenAIEmbeddings(), text_key=upit, namespace=namespace
    # )
    text = "text"

    # verizja sa score-om
    # za prosledjivanje originalnog prompta alatu alternativa je upit
    if st.session_state.input_prompt == True:
        odg = Pinecone(
            index=index,
            embedding=OpenAIEmbeddings(),
            text_key=text,
            namespace=st.session_state.name_semantic,
        ).similarity_search_with_score(
            st.session_state.fix_prompt, k=st.session_state.broj_k
        )
    else:
        odg = Pinecone(
            index=index,
            embedding=OpenAIEmbeddings(),
            text_key=text,
            namespace=st.session_state.name_semantic,
        ).similarity_search_with_score(upit, k=st.session_state.broj_k)

    ceo_odgovor = odg

    # verzija bez score-a
    # odg = Pinecone(
    #    index=index,
    #    embedding=OpenAIEmbeddings(),
    #    text_key=text,
    #    namespace=st.session_state.name_semantic,
    # ).as_retriever(search_kwargs={"k": st.session_state.broj_k})

    # ceo_odgovor = odg.get_relevant_documents(
    #     st.session_state.fix_prompt,
    # )

    odgovor = ""

    for member in ceo_odgovor:
        odgovor += member.page_content + "\n\n"

    return odgovor


# selfquery search - pretrazuje po meta poljima
def selfquery(upit):
    # Initialize Pinecone
    pinecone.init(
        api_key=os.environ["PINECONE_API_KEY"],
        environment=os.environ["PINECONE_API_ENV"],
    )

    llm = ChatOpenAI(temperature=0)
    # Define metadata fields
    metadata_field_info = [
        AttributeInfo(name="title", description="Tema dokumenta", type="string"),
        AttributeInfo(name="keyword", description="reci za pretragu", type="string"),
        AttributeInfo(
            name="text", description="The Content of the document", type="string"
        ),
        AttributeInfo(
            name="source", description="The Source of the document", type="string"
        ),
    ]

    # Define document content description
    document_content_description = "Sistematizacija radnih mesta"

    index_name = "embedings1"
    text = "text"
    # Izbor stila i teme
    index = pinecone.Index(index_name)
    vector = Pinecone.from_existing_index(
        index_name=index_name,
        embedding=OpenAIEmbeddings(),
        text_key=text,
        namespace=st.session_state.name_self,
    )
    ret = SelfQueryRetriever.from_llm(
        llm,
        vector,
        document_content_description,
        metadata_field_info,
        enable_limit=True,
        verbose=True,
        search_kwargs={"k": st.session_state.broj_k},
    )
    # za prosledjivanje originalnog prompta alatu alternativa je upit
    if st.session_state.input_prompt == True:
        ceo_odgovor = ret.get_relevant_documents(st.session_state.fix_prompt)
    else:
        ceo_odgovor = ret.get_relevant_documents(upit)
    odgovor = ""
    for member in ceo_odgovor:
        odgovor += member.page_content + "\n\n"

    return odgovor


# hybrid search - kombinacija semantic i selfquery metoda po kljucnoj reci
def hybrid_query(upit):
    # Initialize Pinecone
    pinecone.init(
        api_key=os.environ["PINECONE_API_KEY_POS"],
        environment=os.environ["PINECONE_ENVIRONMENT_POS"],
    )
    # # Initialize OpenAI embeddings
    embeddings = OpenAIEmbeddings()
    index_name = "bis"

    index = pinecone.Index(index_name)
    bm25_encoder = BM25Encoder().default()

    vectorstore = PineconeHybridSearchRetriever(
        embeddings=embeddings,
        sparse_encoder=bm25_encoder,
        index=index,
        namespace=st.session_state.name_hybrid,
        top_k=st.session_state.broj_k,
        alpha=st.session_state.alpha,
    )
    # za prosledjivanje originalnog prompta alatu alternativa je upit
    if st.session_state.input_prompt == True:
        ceo_odgovor = vectorstore.get_relevant_documents(st.session_state.fix_prompt)
    else:
        ceo_odgovor = vectorstore.get_relevant_documents(upit)

    odgovor = ""
    for member in ceo_odgovor:
        odgovor += member.page_content + "\n\n"

    return odgovor


# if "direct_semantic" not in st.session_state:
#     st.session_state.direct_semantic = None
if "direct_hybrid" not in st.session_state:
    st.session_state.direct_hybrid = None
if "direct_self" not in st.session_state:
    st.session_state.direct_self = None
if "direct_csv" not in st.session_state:
    st.session_state.direct_csv = None


def new_chat():
    st.session_state["generated"] = []
    st.session_state["past"] = []
    st.session_state["input"] = ""
    st.session_state.memory.clear()
    st.session_state["messages"] = []


def main():
    with st.sidebar:
        st.button("New Chat", on_click=new_chat)
        model, temp = init_cond_llm()

        st.session_state.uploaded_file = st.file_uploader(
            "Choose a CSV file", accept_multiple_files=False, type="csv", key="csv_key"
        )
    if st.session_state.uploaded_file is not None:
        with io.open(st.session_state.uploaded_file.name, "wb") as file:
            file.write(st.session_state.uploaded_file.getbuffer())

    if "generated" not in st.session_state:
        st.session_state["generated"] = []
    if "cot" not in st.session_state:
        st.session_state["cot"] = ""
    if "past" not in st.session_state:
        st.session_state["past"] = []
    if "input" not in st.session_state:
        st.session_state["input"] = ""
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    search = GoogleSerperAPIWrapper()

    st.session_state.tools = [
        Tool(
            name="search",
            func=search.run,
            description="Google search tool. Useful when you need to answer questions about recent events or if someone asks for the current time or date.",
        ),
        Tool(
            name="Semantic search",
            func=rag,
            verbose=False,
            description="Useful for when you are asked about topics including Positive doo and their portfolio. Input should contain Positive.",
            return_direct=st.session_state.direct_semantic,
        ),
        Tool(
            name="Hybrid search",
            func=hybrid_query,
            verbose=False,
            description="Useful for when you are asked about topics that will list items about opis radnih mesta.",
            return_direct=st.session_state.direct_hybrid,
        ),
        Tool(
            name="Self search",
            func=selfquery,
            verbose=False,
            description="Useful for when you are asked about topics that will look for keyword.",
            return_direct=st.session_state.direct_self,
        ),
        Tool(
            name="CSV search",
            func=read_csv,
            verbose=True,
            description="Useful for when you are asked about structured data like numbers, counts or sums",
            return_direct=st.session_state.direct_csv,
        ),
    ]

    download_str = []
    if "open_api_key" not in st.session_state:
        # Retrieving API keys from env
        st.session_state.open_api_key = os.environ.get("OPENAI_API_KEY")
    # Read OpenAI API key from env

    if "SERPER_API_KEY" not in st.session_state:
        # Retrieving API keys from env
        st.session_state.SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

    if "memory" not in st.session_state:
        st.session_state.memory = ConversationBufferWindowMemory(
            memory_key="chat_history", return_messages=True, k=4
        )
    if "sistem" not in st.session_state:
        st.session_state.sistem = open_file("prompt_turbo.txt")
    if "odgovor" not in st.session_state:
        st.session_state.odgovor = open_file("odgovor_turbo.txt")
    if "system_message_prompt" not in st.session_state:
        st.session_state.system_message_prompt = (
            SystemMessagePromptTemplate.from_template(st.session_state.sistem)
        )
    if "human_message_prompt" not in st.session_state:
        st.session_state.human_message_prompt = (
            HumanMessagePromptTemplate.from_template("{text}")
        )

    # za prosledjivanje originalnog prompta alatu
    if "fix_prompt" not in st.session_state:
        st.session_state.fix_prompt = ""
    if "chat_prompt" not in st.session_state:
        st.session_state.chat_prompt = ChatPromptTemplate.from_messages(
            [
                st.session_state.system_message_prompt,
                st.session_state.human_message_prompt,
            ]
        )

    name = st.session_state.get("name")

    placeholder = st.empty()

    pholder = st.empty()
    with pholder.container():
        if "stream_handler" not in st.session_state:
            st.session_state.stream_handler = StreamHandler(pholder)
    st.session_state.stream_handler.reset_text()

    chat = ChatOpenAI(
        openai_api_key=st.session_state.open_api_key,
        temperature=temp,
        model=model,
        streaming=True,
        callbacks=[st.session_state.stream_handler],
    )
    upit = []

    if upit := st.chat_input("Postavite pitanje"):
        formatted_prompt = st.session_state.chat_prompt.format_prompt(
            text=upit
        ).to_messages()
        # prompt[0] je system message, prompt[1] je tekuce pitanje
        pitanje = formatted_prompt[0].content + formatted_prompt[1].content

        with placeholder.container():
            st_redirect = StreamlitRedirect()
            sys.stdout = st_redirect
            # za prosledjivanje originalnog prompta alatu
            st.session_state.fix_prompt = formatted_prompt[1].content

            #
            # testirati sa razlicitim agentima i prompt template-ima
            #
            agent_chain = initialize_agent(
                tools=st.session_state.tools,
                llm=chat,
                agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
                messages=st.session_state.chat_prompt,
                verbose=True,
                memory=st.session_state.memory,
                handle_parsing_errors=True,
                max_iterations=4,
            )
            st.write(
                f"Ulaz: {st.session_state.input_prompt}, izlaz: {st.session_state.direct_hybrid}, Alpha: {st.session_state.alpha} "
            )
            output = agent_chain.invoke(input=pitanje)
            output_text = output.get("output", "")

            #            output_text = chat.predict(pitanje)
            st.session_state.stream_handler.clear_text()
            st.session_state.past.append(f"{name}: {upit}")
            st.session_state.generated.append(f"AI Asistent: {output_text}")
            # Calculate the length of the list
            num_messages = len(st.session_state["generated"])

            # Loop through the range in reverse order
            for i in range(num_messages - 1, -1, -1):
                # Get the index for the reversed order
                reversed_index = num_messages - i - 1
                # Display the messages in the reversed order
                st.info(st.session_state["past"][reversed_index], icon="🤔")

                st.success(st.session_state["generated"][reversed_index], icon="👩‍🎓")

                # Append the messages to the download_str in the reversed order
                download_str.append(st.session_state["past"][reversed_index])
                download_str.append(st.session_state["generated"][reversed_index])
            download_str = "\n".join(download_str)

            with st.sidebar:
                st.download_button("Download", download_str)


st_style()
# Koristi se samo za deploy na streamlit.io
deployment_environment = os.environ.get("DEPLOYMENT_ENVIRONMENT")

if deployment_environment == "Streamlit":
    name, authentication_status, username = positive_login(main, " ")
else:
    if __name__ == "__main__":
        main()
