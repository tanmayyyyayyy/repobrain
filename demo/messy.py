import os
import sys
import json


def is_eligible(age, member):
    if age >= 18 and member:
        return True
    else:
        return False


def has_discount(total):
    if total > 100:
        return True
    return False


def valid_emails(users):
    result = []
    for u in users:
        if u != None:
            if "@" in u.get("email", ""):
                result.append(u["email"].lower())
    return result


def shipping_cost(weight, country, express):
    if country == "IN":
        if weight < 1:
            if express:
                return 80
            else:
                return 50
        else:
            if weight < 5:
                if express:
                    return 150
                else:
                    return 100
            else:
                return 200
    else:
        return 500
