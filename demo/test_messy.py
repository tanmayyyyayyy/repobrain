from messy import is_eligible, has_discount, valid_emails, shipping_cost

def test_eligible():
    assert is_eligible(20, True) is True and is_eligible(20, False) is False and is_eligible(10, True) is False

def test_discount():
    assert has_discount(150) is True and has_discount(50) is False

def test_emails():
    users = [{"email": "A@x.com"}, None, {"email": "bad"}]
    assert valid_emails(users) == ["a@x.com"]

def test_shipping():
    assert shipping_cost(0.5, "IN", True) == 80 and shipping_cost(0.5, "IN", False) == 50
    assert shipping_cost(3, "IN", True) == 150 and shipping_cost(3, "IN", False) == 100
    assert shipping_cost(9, "IN", False) == 200 and shipping_cost(1, "US", True) == 500
