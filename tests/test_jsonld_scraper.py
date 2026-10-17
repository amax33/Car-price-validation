from car_market.scrapers.jsonld import JsonLdVehicleScraper


def test_jsonld_parser_extracts_vehicle():
    html = b'''<script type="application/ld+json">{
      "@type":"Vehicle", "sku":"abc", "brand":{"name":"Saipa"}, "model":"Quick",
      "vehicleModelDate":2022, "mileageFromOdometer":{"value":42000},
      "offers":{"price":5500,"areaServed":{"name":"Tehran"}}
    }</script>'''
    row = JsonLdVehicleScraper([], "example")._parse(html, "https://example.test/a")
    assert row is not None
    assert row["source_listing_id"] == "abc"
    assert row["mileage_km"] == 42000


def test_price_units_are_converted_to_million_irr():
    assert JsonLdVehicleScraper([], "x", price_unit="irr")._price({"price": "5,500,000,000"}) == 5500
    assert JsonLdVehicleScraper([], "x", price_unit="toman")._price({"price": 550_000_000}) == 5500


def test_bama_style_product_schema_is_supported():
    html = b'''<script type="application/ld+json">{
      "@type":["Product","Car"], "identifier":"b1", "name":"KMC, SR3",
      "brand":{"name":"KMC"}, "productionDate":1404,
      "description":"a car", "offers":{"price":"4250000000"}
    }</script>'''
    row = JsonLdVehicleScraper([], "bama", price_unit="toman")._parse(html, "https://bama.ir/car/detail-b1")
    assert row is not None
    assert row["model"] == "SR3"
    assert row["asking_price"] == 42500
