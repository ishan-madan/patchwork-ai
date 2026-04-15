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
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, ignore
import requests
import csv
import json
import sys

# Structured output for web frontend
def send_output(message, msg_type="text"):
    payload = {
        "type": msg_type,
        "content": message
    }
    print(json.dumps(payload), flush=True)

def get_input(prompt=""):
    send_output(prompt, "input_prompt")
    return sys.stdin.readline().rstrip("\n")


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
                "subject_name": row.get("subject_lov_descr", "").strip(),
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

    # For each course, collect all matching eval files and attach to ALL instances (by subject+catalog_nbr, not just one crse_id)
    evals_by_key = {}  # key: subj+catnum_nolett, value: list of evals
    if os.path.isdir(eval_dir):
        for fname in os.listdir(eval_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(eval_dir, fname), encoding="utf-8") as f:
                        eval_data = json.load(f)
                        base = fname.split(".")[0]
                        base_main = base.split("_")[0]
                        m = re.match(r"([A-Za-z]+)([0-9]+)", base_main)
                        if m:
                            subj = m.group(1).upper()
                            catnum = m.group(2)
                            key = subj + catnum
                        else:
                            key = base_main.upper()
                        if key not in evals_by_key:
                            evals_by_key[key] = []
                        evals_by_key[key].append(eval_data)
                except Exception:
                    pass  # Ignore malformed eval files

    # Attach aggregated evals to every course instance with matching subject+catalog_nbr (all professors/sections)
    for c in courses.values():
        subj = c["subject"].replace(" ", "").upper()
        catnum = str(c["catalog_nbr"]).replace(" ", "")
        catnum_nolett = re.sub(r"[^0-9]", "", catnum)
        key = subj + catnum_nolett
        evals = evals_by_key.get(key, [])
        c["evaluation"] = evals if evals else None

    return list(courses.values())


def get_unique_subjects(courses):
    subject_map = {}

    for c in courses:
        code = c.get("subject", "").strip()
        name = c.get("subject_name", "").strip()

        if code and code not in subject_map:
            subject_map[code] = name if name else code  # fallback

    return dict(sorted(subject_map.items()))



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
    Units: {c['units']}
    Description: {c['description']}
    Prerequisites: {prereq if prereq else 'None'}
    Evaluation: {eval_summary}
    """)
    return "\n".join(formatted)

def normalize_subject_choice(raw_subject, valid_subjects):
    """
    Ensures the subject returned by the LLM is a valid subject code.
    Handles cases like:
    - "COMPSCI (Computer Science)"
    - "Computer Science"
    - "COMPSCI"
    """

    if not raw_subject:
        return None

    raw_subject = raw_subject.strip()

    # Case 1: Extract code before parentheses
    if "(" in raw_subject:
        raw_subject = raw_subject.split("(")[0].strip()

    raw_upper = raw_subject.upper()

    # Case 2: Direct match (COMPSCI)
    if raw_upper in valid_subjects:
        return raw_upper

    # Case 3: Match by subject name
    for code, name in valid_subjects.items():
        if raw_subject.lower() == name.lower():
            return code

    return None


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
    "subject": "<ONLY the subject code (e.g., COMPSCI). Do NOT include parentheses or full names>"
}}

Available subject codes (with the actual full subject names for reference, but respond with the code only):
{', '.join([f"{k} ({v})" for k, v in subject_list.items()])}
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
    "reason": "Please ensure you meet the prerequisites for this course before enrolling. Here is the course information and prerequisites to help you determine if you are eligible to take this course."
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
    send_output("\nAdvising Session Started.\n", "system")

    courses = load_courses()
    subjects = get_unique_subjects(courses)

    messages = [
        {"role": "system", "content": build_subject_prompt(subjects)}
    ]

    question_count = 0
    chosen_subject = None

    waiting_for_llm = False

    # -------- STAGE 1: SUBJECT SELECTION --------
    while question_count < MAX_QUESTIONS:
        # Notify frontend: waiting for LLM
        if not waiting_for_llm:
            send_output(True, "waiting")
            waiting_for_llm = True
        response = ask_llm(messages)
        # Notify frontend: done waiting
        if waiting_for_llm:
            send_output(False, "waiting")
            waiting_for_llm = False
        try:
            parsed = json.loads(response)
        except:
            send_output("Invalid JSON from LLM:", "system")
            send_output(response, "system")
            return

        if parsed["decision"] == "ask":
            send_output(parsed["question"], "advisor")
            user_input = get_input("")
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": user_input})
            question_count += 1
        elif parsed["decision"] == "choose_subject":
            if question_count < 4:
                send_output("Please ask at least 4 questions before making a recommendation.", "advisor")
                # Force LLM to ask more questions
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": "Please ask me more questions before recommending a subject."})
                continue

            raw_subject = parsed.get("subject", "")
            normalized_subject = normalize_subject_choice(raw_subject, subjects)

            if not normalized_subject:
                send_output("Invalid subject returned. Please select a valid subject code only.", "system")
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": "Please return ONLY a valid subject code from the list."})
                continue

            chosen_subject = normalized_subject

            send_output(
                f"Subject Selected: {chosen_subject} ({subjects[chosen_subject]})",
                "recommendation"
            )
            break

    if not chosen_subject:
        send_output("Unable to determine subject.", "system")
        return

    # -------- STAGE 2: COURSE RECOMMENDATION --------
    subject_courses = [
        c for c in courses if c["subject"] == chosen_subject
    ]

    if not subject_courses:
        send_output("No courses found for that subject.", "system")
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
        # Notify frontend: waiting for LLM
        if not waiting_for_llm:
            send_output(True, "waiting")
            waiting_for_llm = True
        final_response = ask_llm(messages)
        # Notify frontend: done waiting
        if waiting_for_llm:
            send_output(False, "waiting")
            waiting_for_llm = False
        try:
            parsed = json.loads(final_response)
        except:
            send_output("Invalid JSON in recommendation stage:", "system")
            send_output(final_response, "system")
            return

        if parsed["decision"] == "check_prerequisites":
            crse_id = parsed["crse_id"]
            reason = parsed.get("reason", "")
            match = next((c for c in subject_courses if c["crse_id"] == crse_id), None)
            if match:
                prereq = match.get("prerequisite", "")
                if prereq:
                    send_output({
                        "course": f"{match['subject']} {match['catalog_nbr']}",
                        "title": match["title"],
                        "units": match["units"],
                        "career": match["career"],
                        "reason": reason
                    }, "course_card")
                    display_prereq = re.sub(r"^Prerequisite[s]?:\s*", "", prereq, flags=re.IGNORECASE)
                    send_output(f"Prerequisites for this course: {display_prereq}", "system")
                    prereq_met = get_input("Have you met these prerequisites? (yes/no): ").strip().lower()
                else:
                    send_output("No prerequisites listed for the potential course recommendation.", "system")
                    prereq_met = "yes"
                messages.append({"role": "assistant", "content": final_response})
                messages.append({"role": "user", "content": f"I {'have' if prereq_met in ['yes','y'] else 'have not'} met the prerequisites."})
                tried_courses.add(normalize_course_key(match))
                if prereq_met not in ["yes", "y"]:
                    send_output("You must meet the prerequisites before taking this course. Let's try another recommendation.", "advisor")
                    filtered_courses = [c for c in subject_courses if normalize_course_key(c) not in tried_courses]
                    course_text = courses_to_string(filtered_courses)
                    messages.append({
                        "role": "system",
                        "content": build_recommendation_prompt(course_text)
                    })
                    continue
            else:
                send_output(f"Course ID: {crse_id}", "system")
                send_output(reason, "system")
                continue

        elif parsed["decision"] == "recommend":
            crse_id = parsed["crse_id"]
            reason = parsed["reason"]
            match = next((c for c in subject_courses if c["crse_id"] == crse_id), None)

            send_output("Recommended Course", "recommendation")
            if match:
                send_output({
                    "course": f"{match['subject']} {match['catalog_nbr']}",
                    "title": match["title"],
                    "units": match["units"],
                    "career": match["career"],
                    "reason": reason
                }, "course_card")
                tried_courses.add(normalize_course_key(match))
            else:
                send_output(f"Course ID: {crse_id}", "system")
                send_output(reason, "system")

            user_feedback = get_input("Do you want to take this course? (yes/no): ").strip().lower()
            if user_feedback in ["yes", "y"]:
                send_output("Thank you! Good luck with your studies.", "system")
                break
            else:
                send_output("Okay, let's try another recommendation. Please tell me why you don't want this course or what you would prefer instead.", "advisor")
                feedback = get_input("")
                messages.append({"role": "assistant", "content": final_response})
                messages.append({"role": "user", "content": feedback})
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