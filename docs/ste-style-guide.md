# The writing standard: ASD-STE100 Simplified Technical English

Use these rules for every README and for `docs/ste-style-guide.md` in each repository. Copy this file
into the repository as `docs/ste-style-guide.md` and add a **project vocabulary** section (Section 3)
with the technical names and technical verbs of that project.

## 1. The writing rules

### Words

1. Use one word for one meaning, and one meaning for one word. Do not use synonyms for variety.
2. Use a word only as one part of speech. For example, `test` is a noun or a verb, `check` is a verb.
3. Do not use phrasal verbs (`set up`, `carry out`, `find out`, `pick up`, `look up`, `come up with`).
   Use one verb: `prepare`, `do`, `find`, `get`, `make`.
4. Do not use an `-ing` form as a noun or an adjective (`the running job`, `after indexing`).
   Exception: a technical name, a file name, a command or a status value.
5. Do not use contractions (`don't`, `it's`, `can't`). Do not use slang or idioms
   (`out of the box`, `under the hood`, `at a glance`, `gotcha`, `bells and whistles`).
6. Do not use `and/or`. Write `A, B or both`.
7. Do not use `should`, `could`, `would` or `may` for instructions. Use `must` for a rule, the
   imperative for a step and `can` for a possibility.
8. Keep the articles `a`, `an` and `the` in sentences.
9. Do not make a noun cluster of more than three words. A technical name is one word.

### Sentences

1. A procedural sentence (an instruction) has a maximum of **20 words**.
2. A descriptive sentence has a maximum of **25 words**.
3. Write one instruction in one sentence.
4. Use the imperative for an instruction: `Run the tests.` Not `The tests should be run.`
5. Use the active voice. Use the passive voice only when the agent of the action is not important.
6. Use only the simple present, the simple past and the simple future.
7. Put a condition before the instruction: `If the index is stale, build it again.`
8. Do not use semicolons in sentences. Write two sentences.

### Paragraphs, notes and warnings

1. A paragraph has one topic and a maximum of **6 sentences**. Start with the topic sentence.
2. A warning or a caution starts with a clear command. Then it gives the reason.
3. A note gives information. It does not give an instruction.
4. Use a vertical list for a sequence or a set of conditions. Each item of a numbered procedure is one step.

### Tables, headings and diagrams

1. A table cell can be a short phrase. If a cell has a sentence, the sentence obeys the rules.
2. A heading is a noun phrase (`The cost model`) or an imperative (`Run the demo`).
   Do not start a heading with an `-ing` form.
3. A diagram label is a short phrase. Use the same terms as the text.

### What STE does not change

Code, commands, file names, paths, field names, environment variables, status values, enum values,
product names and URLs stay exactly as they are. They are technical names. Put them in backticks.

## 2. General words to replace

| Do not use | Use |
|---|---|
| utilize, leverage | use |
| in order to | to |
| set up | prepare, install, configure |
| carry out, perform | do |
| make sure, ensure | make sure (allowed), or "check that" |
| a lot of, lots of | many, much |
| e.g., i.e. | for example, that is |
| should (instruction) | must (rule) / imperative (step) |
| might, may (possibility) | can |
| very, really, just, simply, easily | (delete) |
| seamless, robust, powerful, blazing | (delete or give a measured fact) |

## 3. Project vocabulary

This section gives the technical names and the technical verbs of studybuddy-rag. The README uses each term with only this meaning.

### 3.1 Technical names (nouns)

| Term | Meaning | Do not use |
|---|---|---|
| **question** | The text that a student sends to the tutor | query, prompt, request |
| **answer** | The text that the tutor gives for one question | response, reply (a **reply** is only the raw output of the classifier) |
| **reply** | The raw text that the LLM gives to the classification call | answer, output |
| **subject** | One label of `Subject`: `arts`, `mathematics`, `science` or `general` | topic, category, class, domain |
| **corpus** | The folder of Markdown documents with the study material | knowledge base, dataset, library |
| **study material** | The content of the corpus, as the student sees it | course content, textbook |
| **document** | One Markdown file in the corpus | file (when the content is meant), source file |
| **section** | The text under one `#` heading of a document | part, paragraph |
| **chunk** | A group of whole sentences from one section, at most 120 words | passage, snippet, segment, block |
| **source** | One retrieved chunk with a number in the answer prompt | reference, context, document |
| **citation** | A `[n]` mark in an answer that points to source number n | reference, footnote, link |
| **index** | The `HybridIndex`: chunks, vectors and BM25 statistics | vector store, database (for the chunks) |
| **embedder** | A provider that changes a text into a normalised vector | encoder, embedding model, vectorizer |
| **vector** | The list of numbers that the embedder gives for one text | embedding, encoding |
| **centroid** | The mean vector of the chunks of one subject | prototype, cluster centre |
| **route decision** | The `RouteDecision` that the router gives | classification result, routing output |
| **router** | `LLMRouter` or `CentroidRouter` | classifier (only for the LLM call), dispatcher |
| **tutor** | The `Tutor` class that gives the answer | bot, assistant, agent |
| **grounded answer** | An answer with at least one valid citation | supported answer, verified answer |
| **ungrounded answer** | An answer with no valid citation | hallucination, unsupported answer |
| **provider** | An LLM, embedder or speech-to-text implementation behind an interface | backend, vendor, plugin |
| **fake** | A deterministic offline provider | mock, stub, dummy |
| **session** | A login with a token and an expiry time | connection, login state |
| **token** | The random string that identifies a session | key, cookie, password |
| **principal** | The authenticated user of a call | caller, account, current user |
| **student**, **instructor** | The two roles | pupil, learner, teacher, admin |
| **aggregate** | A count or an average over a group of at least k students | statistic, summary (a **grade summary** is a text) |
| **k-anonymity threshold** | The minimum group size k for an aggregate | privacy limit, minimum count |
| **query log** | The `query_log` table | history table, audit log |
| **demo user** | A synthetic account that `seed_demo` makes | test user, sample user |

### 3.2 Technical verbs

| Verb | Meaning |
|---|---|
| **authenticate** | Find the principal of a session token and check the expiry time |
| **route** | Give a question one subject |
| **retrieve** | Get the top-k chunks for a question from the index |
| **embed** | Change a text into a vector |
| **cite** | Put a `[n]` mark in an answer |
| **ingest** | Read the corpus, make chunks and save the index |
| **record** | Write one row in `query_log` |
| **purge** | Delete the `query_log` rows that are older than the retention period |
| **hide** | Not show an aggregate because its group has fewer than k members |
| **seed** | Write the demo users, courses and grades into the database |
| **evaluate** | Measure the router, the retrieval and the citation rate on the eval set |
| **transcribe** | Change recorded audio into question text |
