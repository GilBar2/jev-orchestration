from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient, Choice, Score, Noul

load_dotenv()  # reads TYPESAFE_API_KEY from ~/jev/.env

with TypeSafeClient() as client:
    res = client.system_one(
        state="My card was charged twice for the same order, please refund one.",
        questions={
            "intent": Choice(criteria={"billing": None, "shipping": None, "tech_support": None}),
            "urgency": Score(criteria=["How urgent is this ticket?"]),
            "is_refund": Noul(instructions="Is the customer asking for a refund?"),
        },
    )
    print(res)
