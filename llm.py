"""
Duke Course Advisor
------------------------------------
Two-Stage LLM Filtering Architecture

Stage 1:
- LLM asks student up to 5 questions
- LLM selects most relevant subject code

Stage 2:
- Python filters courses by subject
- LLM selects best course from that subject

Requires:
- course_offerings.csv
- course_attributes.csv
- terms_offered.csv

Environment variable required:
export LITELLM_TOKEN="sk-xxxxxxxx"
"""

import os
import requests
import csv
import json


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

DUKE_CHAT_URL = "https://litellm.oit.duke.edu/chat/completions"
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_TIMEOUT_SEC = 30
MAX_QUESTIONS = 5


COURSE_FILE = "data/course_offerings.csv"
ATTR_FILE = "data/course_attributes.csv"
TERM_FILE = "data/terms_offered.csv"
EVALS_DIR = "data/course_evaluations"


# --------------------------------------------------
# TOKEN + LLM CALL
# --------------------------------------------------

def get_token():
    token = os.getenv("LITELLM_TOKEN", "").strip()
    if token == "":
        raise RuntimeError("Missing LITELLM_TOKEN environment variable.")
    return token


def ask_llm(messages, model=DEFAULT_MODEL):
    token = get_token()

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "x-litellm-api-key": token,
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    last_exception = None
    for attempt in range(2):
        try:
            resp = requests.post(
                DUKE_CHAT_URL,
                headers=headers,
                json=payload,
                timeout=DEFAULT_TIMEOUT_SEC,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                last_exception = RuntimeError(resp.text)
        except Exception as e:
            last_exception = e
    # If we get here, both attempts failed
    raise last_exception


# --------------------------------------------------
# LOAD + MERGE COURSE DATA
# --------------------------------------------------


def load_courses():
    courses = {}

    # Load main course offerings
    with open(COURSE_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            crse_id = row["crse_id"]
            descr = row.get("descrlong", "")
            # Extract prerequisite from descrlong if present
            import re
            prereq = ""
            m = re.search(r"(Prerequisite[s]?:.*)$", descr, re.IGNORECASE)
            if m:
                prereq = m.group(1).strip()
            courses[crse_id] = {
                "crse_id": crse_id,
                "subject": row.get("subject", "").strip(),
                "catalog_nbr": row.get("catalog_nbr", "").strip(),
                "title": row.get("course_title_long", "").strip(),
                "description": descr[:500],
                "units": row.get("units_minimum", "").strip(),
                "career": row.get("acad_career_lov_descr", "").strip(),
                "grading": row.get("grading_basis_lov_descr", "").strip(),
                "attributes": [],
                "terms_offered": [],
                "evaluation": None,  # Will be filled in below
                "prerequisite": prereq
            }

    # Load attributes
    with open(ATTR_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            crse_id = row["crse_id"]
            if crse_id in courses:
                attr_name = row.get("crse_attr_lov_descr", "")
                attr_value = row.get("crse_attr_value_lov_descr", "")
                combined = f"{attr_name} - {attr_value}".strip(" -")
                if combined:
                    courses[crse_id]["attributes"].append(combined)

    # Load terms offered
    with open(TERM_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            crse_id = row["crse_id"]
            if crse_id in courses:
                term = row.get("strm_lov_descr", "").strip()
                if term:
                    courses[crse_id]["terms_offered"].append(term)

    # Load and aggregate course evaluations (JSON files)
    eval_dir = EVALS_DIR
    # Map from (subject+catalog_nbr_no_letters) to crse_id
    import re
    subjcat_to_crseid = {}
    for c in courses.values():
        # Remove all spaces and trailing letters from catalog_nbr (e.g., 101L -> 101)
        subj = c["subject"].replace(" ","").upper()
        catnum = str(c["catalog_nbr"]).replace(" ","")
        catnum_nolett = re.sub(r"[^0-9]", "", catnum)
        key = subj + catnum_nolett
        subjcat_to_crseid.setdefault(key, []).append(c["crse_id"])

    # For each course, collect all matching eval files
    evals_by_crse_id = {crse_id: [] for crse_id in courses}
    if os.path.isdir(eval_dir):
        for fname in os.listdir(eval_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(eval_dir, fname), encoding="utf-8") as f:
                        eval_data = json.load(f)
                        base = fname.split(".")[0]
                        # Remove trailing _2, _3, etc for matching
                        base_main = base.split("_")[0]
                        # Normalize: extract subject and number, ignore trailing letters
                        m = re.match(r"([A-Za-z]+)([0-9]+)", base_main)
                        if m:
                            subj = m.group(1).upper()
                            catnum = m.group(2)
                            key = subj + catnum
                        else:
                            key = base_main.upper()
                        matched = False
                        if key in subjcat_to_crseid:
                            for crse_id in subjcat_to_crseid[key]:
                                evals_by_crse_id[crse_id].append(eval_data)
                                matched = True
                        # Fallback: try to match by crse_id in JSON
                        if not matched and isinstance(eval_data, dict) and "crse_id" in eval_data:
                            crse_id = eval_data["crse_id"]
                            if crse_id in courses:
                                evals_by_crse_id[crse_id].append(eval_data)
                except Exception as e:
                    pass  # Ignore malformed eval files

    # Attach aggregated evals to each course
    for crse_id, eval_list in evals_by_crse_id.items():
        if eval_list:
            courses[crse_id]["evaluation"] = eval_list
        else:
            courses[crse_id]["evaluation"] = None

    return list(courses.values())


def get_unique_subjects(courses):
    return sorted(set(c["subject"] for c in courses if c["subject"]))



def summarize_evaluation(eval_data):
    if not eval_data:
        return "No evaluation data available."
    # If multiple evals, aggregate
    evals = eval_data if isinstance(eval_data, list) else [eval_data]
    ratings = []
    comments = []
    for ed in evals:
        if isinstance(ed, dict):
            if "average_rating" in ed:
                try:
                    ratings.append(float(ed["average_rating"]))
                except Exception:
                    pass
            if "comments" in ed and isinstance(ed["comments"], list):
                comments.extend(ed["comments"])
    summary = []
    if ratings:
        avg_rating = sum(ratings) / len(ratings)
        summary.append(f"Average Rating (across {len(ratings)} evals): {avg_rating:.2f}")
    if comments:
        # Show up to 2 sample comments
        for i, comment in enumerate(comments[:2], 1):
            summary.append(f"Comment {i}: {comment}")
    return " ".join(summary) if summary else "No evaluation data available."

def courses_to_string(courses):
    formatted = []
    for c in courses:
        eval_summary = summarize_evaluation(c.get("evaluation"))
        prereq = c.get("prerequisite", "")
        formatted.append(f"""
    Course ID: {c['crse_id']}
    Code: {c['subject']} {c['catalog_nbr']}
    Title: {c['title']}
    Career: {c['career']}
    Units: {c['units']}
    Grading: {c['grading']}
    Attributes: {', '.join(c['attributes'])}
    Terms Offered: {', '.join(set(c['terms_offered']))}
    Description: {c['description']}
    Prerequisites: {prereq if prereq else 'None'}
    Evaluation: {eval_summary}
    """)
    return "\n".join(formatted)


# --------------------------------------------------
# PROMPTS
# --------------------------------------------------

def build_subject_prompt(subject_list):
        return f"""
You are a university academic advisor.

Your job:
- Ask the student about their academic interests, career goals,
    experience level, and preferences.
- Ask ONE question at a time.
- Ask AT LEAST 4 questions, and NO MORE than 5 total questions before making a recommendation.

After gathering enough information (minimum 4 questions),
choose the MOST appropriate subject code from the list below.

Respond ONLY in JSON.

If you need more information:
{{
    "decision": "ask",
    "question": "<your question>"
}}

If ready to choose a subject (only after at least 4 questions):
{{
    "decision": "choose_subject",
    "subject": "<exact subject code from list>"
}}

Available subject codes:
{', '.join(subject_list)}
"""



def build_recommendation_prompt(course_text):
    return f"""
Based on the student's previous answers and any feedback about previous recommendations,
choose the BEST course from the list below. If the student rejected a previous course, do NOT recommend it again and use their feedback to improve your next suggestion.

You have access to course evaluation data for each course (see the 'Evaluation' field). Use this data to help determine if a course fits the student's needs and preferences. For example, if a student wants a highly rated course or cares about student feedback, use the evaluation data to inform your recommendation.

When you are ready to recommend a course, but BEFORE finalizing the recommendation, output the following JSON to the terminal:

{{
    "decision": "check_prerequisites",
    "crse_id": "<crse_id>",
    "reason": "<why you are considering this course>"
}}

After the user confirms they have met the prerequisites, you will then output the final recommendation as before:

{{
    "decision": "recommend",
    "crse_id": "<crse_id>",
    "reason": "<clear explanation tied to the student's goals, feedback, and the course evaluation data>"
}}

Courses:
{course_text}
"""


# --------------------------------------------------
# MAIN CONVERSATION
# --------------------------------------------------

def run_advisor():
    print("\n🎓 Duke AI Course Advisor\n")

    courses = load_courses()
    subjects = get_unique_subjects(courses)

    messages = [
        {"role": "system", "content": build_subject_prompt(subjects)}
    ]

    question_count = 0
    chosen_subject = None

    # -------- STAGE 1: SUBJECT SELECTION --------
    while question_count < MAX_QUESTIONS:
        response = ask_llm(messages)
        try:
            parsed = json.loads(response)
        except:
            print("Invalid JSON from LLM:")
            print(response)
            return

        if parsed["decision"] == "ask":
            print("\nAdvisor:", parsed["question"])
            user_input = input("You: ")
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": user_input})
            question_count += 1
        elif parsed["decision"] == "choose_subject":
            if question_count < 4:
                print("\nAdvisor: Please ask at least 4 questions before making a recommendation.")
                # Force LLM to ask more questions
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": "Please ask me more questions before recommending a subject."})
                continue
            chosen_subject = parsed["subject"]
            print(f"\n📚 Subject Selected: {chosen_subject}")
            break

    if not chosen_subject:
        print("Unable to determine subject.")
        return

    # -------- STAGE 2: COURSE RECOMMENDATION --------
    subject_courses = [
        c for c in courses if c["subject"] == chosen_subject
    ]

    if not subject_courses:
        print("No courses found for that subject.")
        return

    course_text = courses_to_string(subject_courses)

    messages.append({
        "role": "system",
        "content": build_recommendation_prompt(course_text)
    })

    import re
    def normalize_course_key(course):
        subj = course["subject"].replace(" ","").upper()
        catnum = str(course["catalog_nbr"]).replace(" ","")
        catnum_nolett = re.sub(r"[^0-9]", "", catnum)
        return subj + catnum_nolett

    tried_courses = set()

    while True:
        final_response = ask_llm(messages)
        try:
            parsed = json.loads(final_response)
        except:
            print("Invalid JSON in recommendation stage:")
            print(final_response)
            return

        if parsed["decision"] == "check_prerequisites":
            crse_id = parsed["crse_id"]
            reason = parsed.get("reason", "")
            match = next((c for c in subject_courses if c["crse_id"] == crse_id), None)
            if match:
                print(f"\n🔎 Prerequisite Check for {match['subject']} {match['catalog_nbr']} — {match['title']}")
                prereq = match.get("prerequisite", "")
                if prereq:
                    # Remove the 'Prerequisite:' or 'Prerequisites:' prefix for display
                    import re
                    display_prereq = re.sub(r"^Prerequisite[s]?:\s*", "", prereq, flags=re.IGNORECASE)
                    print(f"\nPrerequisites for this course: {display_prereq}")
                else:
                    print("\nNo prerequisites listed for this course.")
                prereq_met = input("Have you met these prerequisites? (yes/no): ").strip().lower()
                # Add user response to messages for LLM context
                messages.append({"role": "assistant", "content": final_response})
                messages.append({"role": "user", "content": f"I {'have' if prereq_met in ['yes','y'] else 'have not'} met the prerequisites."})
                # Mark this course as tried regardless of user response
                tried_courses.add(normalize_course_key(match))
                if prereq_met not in ["yes", "y"]:
                    print("\nAdvisor: You must meet the prerequisites before taking this course. Let's try another recommendation.")
                    # Refresh the system prompt to exclude tried courses and include feedback
                    filtered_courses = [c for c in subject_courses if normalize_course_key(c) not in tried_courses]
                    course_text = courses_to_string(filtered_courses)
                    messages.append({
                        "role": "system",
                        "content": build_recommendation_prompt(course_text)
                    })
                    continue
            else:
                print("Course ID:", crse_id)
                print(reason)
                # If we can't find the course, skip
                continue

        elif parsed["decision"] == "recommend":
            crse_id = parsed["crse_id"]
            reason = parsed["reason"]
            match = next((c for c in subject_courses if c["crse_id"] == crse_id), None)

            print("\n✅ Recommended Course\n")
            if match:
                print(f"{match['subject']} {match['catalog_nbr']} — {match['title']}")
                print(f"Units: {match['units']}")
                print(f"Career: {match['career']}")
                print("\nWhy this course?")
                print(reason)
                tried_courses.add(normalize_course_key(match))
            else:
                print("Course ID:", crse_id)
                print(reason)

            user_feedback = input("\nDo you want to take this course? (yes/no): ").strip().lower()
            if user_feedback in ["yes", "y"]:
                print("\nThank you! Good luck with your studies.")
                break
            else:
                print("\nAdvisor: Okay, let's try another recommendation. Please tell me why you don't want this course or what you would prefer instead.")
                feedback = input("You: ")
                messages.append({"role": "assistant", "content": final_response})
                messages.append({"role": "user", "content": feedback})
                # Refresh the system prompt to exclude tried courses and include feedback
                filtered_courses = [c for c in subject_courses if normalize_course_key(c) not in tried_courses]
                course_text = courses_to_string(filtered_courses)
                messages.append({
                    "role": "system",
                    "content": build_recommendation_prompt(course_text)
                })


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    run_advisor()