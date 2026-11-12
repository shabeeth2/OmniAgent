"""Bounded questions and answers shared by the graph and HTTP boundary."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64)
    q: str = Field(min_length=1, max_length=500)
    type: Literal['radio', 'check']
    options: list[str] = Field(max_length=8)

    @model_validator(mode='after')
    def unique_options(self):
        if any(not value.strip() or len(value) > 300 for value in self.options):
            raise ValueError('Options must contain 1–300 characters')
        if len(set(self.options)) != len(self.options):
            raise ValueError('Options must be unique')
        return self


class Questions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    questions: list[Question] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError('Question IDs must be unique')
        return self


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    question_id: str = Field(min_length=1, max_length=64)
    selected: list[int] = Field(max_length=8)
    custom: str = Field(max_length=2000)
    skipped: bool


class Answers(BaseModel):
    model_config = ConfigDict(extra='forbid')
    answers: list[Answer] = Field(min_length=1, max_length=3)


def validate_answers(questions: list[dict], submission: Answers) -> list[dict]:
    """Reject contradictions; include labels so the model never guesses index meaning."""
    questions = Questions(questions=questions).questions
    answers = {answer.question_id: answer for answer in submission.answers}
    if len(answers) != len(submission.answers) or set(answers) != {q.id for q in questions}:
        raise ValueError('Answer every question exactly once, or mark it skipped')
    result = []
    for question in questions:
        answer = answers[question.id]
        if len(set(answer.selected)) != len(answer.selected) or any(i < 0 or i >= len(question.options) for i in answer.selected):
            raise ValueError('Invalid option index')
        if question.type == 'radio' and len(answer.selected) + bool(answer.custom) > 1:
            raise ValueError('Single-choice questions accept one option or a custom answer')
        if answer.skipped == bool(answer.selected or answer.custom):
            raise ValueError('Skipped answers must be empty; other answers must have a value')
        result.append({**answer.model_dump(), 'question': question.q,
                       'selected_labels': [question.options[i] for i in answer.selected]})
    return result


def answer_summary(answers: list[dict]) -> str:
    return '\n\n'.join(f"{answer['question']}\n" + (
        'Skipped (unanswered)' if answer['skipped'] else
        '; '.join(answer['selected_labels'] + ([answer['custom']] if answer['custom'] else []))
    ) for answer in answers)
