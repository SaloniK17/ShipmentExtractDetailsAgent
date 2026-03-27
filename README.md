Problem

When an email contains multiple shipment details, the model may mix values across different shipment lines.

This mainly impacts:

cargo_weight_kg
cargo_cbm
origin / destination pairing

As a result, the extracted shipment can become inconsistent.

Solution

The prompt was optimized with a stricter rule for multiple shipment handling:

First identify the selected shipment
Then extract all fields only from that same shipment
Do not mix CBM, weight, incoterm, or dangerous goods across different shipment lines
Conclusion

By improving the prompt rules, the extraction became more shipment-consistent and reliable.

This helps ensure that all extracted fields belong to the same shipment entry, improving accuracy for emails containing multiple shipment lanes.
