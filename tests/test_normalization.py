from car_market.normalization import normalize_make, normalize_model, normalize_year, parse_number


def test_persian_values_are_normalized():
    assert normalize_make(" ايران خودرو ") == "Iran Khodro"
    assert normalize_model("دنا پلاس") == "Dena Plus"
    assert normalize_year("۱۴۰۲") == 2023
    assert parse_number("۱۲۳,۴۵۶ کیلومتر") == 123456

