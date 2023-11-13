
def our_custom_agent(question: str, session_state: dict):
    from langchain.agents import (
        Tool,
        AgentType,
        AgentExecutor,
        LLMSingleActionAgent,
        AgentOutputParser,
        create_csv_agent,
    )
    from langchain.chains import LLMChain
    from langchain.chat_models import ChatOpenAI
    from langchain.prompts.chat import (
        SystemMessagePromptTemplate,
        HumanMessagePromptTemplate,
        ChatPromptTemplate,
        StringPromptTemplate,
    )
    from langchain.schema import (
        AgentAction,
        AgentFinish,
        OutputParserException,
    )
    from langchain.utilities import GoogleSerperAPIWrapper

    from os import environ
    from json import dumps
    from re import search, DOTALL
    from typing import List, Union
    from openai import Embedding
    import pinecone
    from pinecone_text.sparse import BM25Encoder
    from myfunc.mojafunkcija import open_file

    environ.get("OPENAI_API_KEY")

    # Tool #1 Web search
    web_search = GoogleSerperAPIWrapper(environment=environ["SERPER_API_KEY"])


    # Tools #2 & #3 Pinecone Hybrid search
    def hybrid_search_process_alpha1(upit):
        return hybrid_search_process(upit, 0.1)


    def hybrid_search_process_alpha2(upit):
        return hybrid_search_process(upit, 0.9)
    

    def hybrid_search_process(upit, alpha):
        pinecone.init(
            api_key=environ["PINECONE_API_KEY_POS"],
            environment=environ["PINECONE_ENVIRONMENT_POS"],
        )
        index = pinecone.Index("bis")

        def hybrid_query():
            get_embedding = (
                lambda text, model="text-embedding-ada-002": Embedding.create(
                    input=[text.replace("\n", " ")],
                    model=model,
                )["data"][0]["embedding"]
            )

            hybrid_score_norm = (
                lambda dense, sparse, alpha: (
                    [v * alpha for v in dense],
                    {
                        "indices": sparse["indices"],
                        "values": [v * (1 - alpha) for v in sparse["values"]],
                    },
                )
                if 0 <= alpha <= 1
                else ValueError("Alpha must be between 0 and 1")
            )

            hdense, hsparse = hybrid_score_norm(
                sparse = BM25Encoder().fit([upit]).encode_queries(upit),
                dense=get_embedding(upit),
                alpha=alpha,
            )

            return index.query(
                top_k=session_state["broj_k"],
                vector=hdense,
                sparse_vector=hsparse,
                include_metadata=True,
                namespace=session_state["namespace"],
                ).to_dict()

        session_state["tematika"] = hybrid_query()

        uk_teme = ""
        for _, item in enumerate(session_state["tematika"]["matches"]):
            if item["score"] > 0.05:    # session_state["score"]
                uk_teme += item["metadata"]["context"] + "\n\n"

        system_message = SystemMessagePromptTemplate.from_template(
            template=session_state["stil"]
            ).format()

        human_message = HumanMessagePromptTemplate.from_template(
            template=open_file("prompt_FT.txt")
            ).format(
                zahtev=question,
                uk_teme=uk_teme,
                ft_model=session_state["model"],
                )

        return ChatPromptTemplate(messages=[system_message, human_message])

    # Tool #4 CSV search
    def csv_file_analyzer(upit):
        if session_state["uploaded_file"]:
            csv_agent = create_csv_agent(
                ChatOpenAI(temperature=0.0, model_name="gpt-4", verbose=True),
                session_state["uploaded_file"].name,
                verbose=True,
                agent_type=AgentType.OPENAI_FUNCTIONS,
                handle_parsing_errors=True,
            )
            return str(csv_agent.run(dumps({"input": upit})))
        else:
            return "Niste odabrali CSV fajl za pretragu."


    # All Tools
    tools = [
        Tool(
            name="Web search",
            func=web_search.run,
            verbose=True,
            description="""
            This tool uses Google Search to find the most relevant and up-to-date information on the web. \
            This tool is particularly useful when you need comprehensive information on a specific topic, \
            want to explore different viewpoints, or are looking for the latest news and data.
            Please note that the quality and relevance of results may depend on the specificity of your query. Never use this tool when asked about Positive doo.
            """,
        ),
        Tool(
            name="Pinecone Keyword search",
            func=hybrid_search_process_alpha1,
            verbose=True,
            description="""
            The Keyword Search tool is used to find exact matches for the terms in your query. \
            It scans through the data and retrieves all instances where the keywords appear. \
            This makes it particularly useful when you are looking for specific information and know the exact terms to search for.
            However, it may not capture all relevant information if synonyms or related terms are used instead of the exact keywords. \
            Please note that the quality and relevance of results may depend on the specificity of your query. This tool is relevant if the query is about Positive doo.
            """,
            ),
        Tool(
            name="Pinecone Semantic search",
            func=hybrid_search_process_alpha2,
            verbose=True,
            description="""
            The Semantic Search tool is used to understand the intent and contextual meaning of a query. \
            By analyzing the semantics of the query, it can retrieve information that is not just keyword-based but also contextually relevant. \
            This makes it particularly useful when dealing with complex queries or when searching for information in large, unstructured data sets. 
            Please note that the quality and relevance of results may depend on the specificity of your query. 
            This tool is relevant if the query is about Positive doo.
            """,
            ),
        Tool(
            name="CSV search",
            func=csv_file_analyzer,
            verbose=True,
            description="""
            This tool should be use when you are asked about structured data, e.g: numbers, counts or sums. This tool is relevant if the query is about Positive doo.
            Extremely important: when using this tool send it only the python code (with lowercase when searching for matches) that solves the problem. \
            Do not send any extra text/explanations.
            """,
            direct_output=True,
            ),
        ]

    template = """Answer the following questions as best you can. You have access to the following tools:
    {tools}

    Only answer questions using the tools above. If you can't use a tool to answer a question, say "I don't know".
    Use the following format:

    Question: the input question you must answer
    Thought: you should always think about what to do
    Action: the action to take, should be one of [{tool_names}]
    Action Input: the input to the action
    Observation: the result of the action
    ... (this Thought/Action/Action Input/Observation can repeat multiple times, if necessary)
    Thought: I now know the final answer
    Final Answer: the final answer to the original input question; ALWAYS write in Serbian language

    One very important information: if you get a Python code from the tool, you should invoke that code to the tool to give the results.
    Begin!

    Question: {input}
    {agent_scratchpad}"""

    class CustomPromptTemplate(StringPromptTemplate):
        template: str
        tools: List[Tool]

        def format(self, **kwargs) -> str:
            intermediate_steps = kwargs.pop(
                "intermediate_steps"
            )  # Get the intermediate steps (AgentAction, Observation tuples)

            kwargs["agent_scratchpad"] = "".join(
                [
                    f"{action.log}\nObservation: {observation}\nThought: "
                    for action, observation in intermediate_steps
                ]
            )
            kwargs["tools"] = "\n".join(
                [f"{tool.name}: {tool.description}" for tool in self.tools]
            )
            kwargs["tool_names"] = ", ".join([tool.name for tool in self.tools])

            return self.template.format(**kwargs)

    class CustomOutputParser(AgentOutputParser):
        def parse(self, llm_output: str) -> Union[AgentAction, AgentFinish]:
            if "Final Answer:" in llm_output:
                return AgentFinish(
                    # Return values is a dictionary with a single `output` key
                    return_values={
                        "output": llm_output.split("Final Answer:")[-1].strip()
                    },
                    log=llm_output,
                )
            match = search(
                pattern=r"Action\s*\d*\s*:(.*?)\nAction\s*\d*\s*Input\s*\d*\s*:[\s]*(.*)",
                string=llm_output,
                flags=DOTALL,
            )
            if not match:
                raise OutputParserException(
                    f"Could not parse LLM output: `{llm_output}`"
                )

            # action, action input and logs
            return AgentAction(
                tool=match.group(1).strip(),
                tool_input=match.group(2).strip(" ").strip('"'),
                log=llm_output,
            )

    llm_chain = LLMChain(
        llm=ChatOpenAI(temperature=0, model_name="gpt-4", verbose=True),
        prompt=CustomPromptTemplate(
            template=template,
            tools=tools,
            input_variables=["input", "intermediate_steps"],
        ),
    )

    agent = LLMSingleActionAgent(
        llm_chain=llm_chain,
        output_parser=CustomOutputParser(),
        stop=["\nObservation:"],
        allowed_tools=[tool.name for tool in tools],
    )

    return AgentExecutor.from_agent_and_tools(
        agent=agent, tools=tools, verbose=True
    ).run(question)