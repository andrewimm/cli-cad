"""Print GitHub Actions error annotations for failed tests in a JUnit XML report (CI helper).

Annotations show on the run page and in pull requests without log access:
    python scripts/junit_annotations.py junit.xml
"""

import sys
import xml.etree.ElementTree as ET


def main(path: str) -> None:
    root = ET.parse(path).getroot()
    n = 0
    for case in root.iter("testcase"):
        for bad in list(case.findall("failure")) + list(case.findall("error")):
            n += 1
            name = f"{case.get('classname')}.{case.get('name')}"
            title = name.replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
            text = (bad.get("message") or "") + "\n" + (bad.text or "")
            lines = [ln for ln in text.strip().splitlines() if ln.strip()]
            body = "%0A".join(ln.replace("%", "%25").replace("\r", "") for ln in lines[-25:])  # the end of the traceback
            print(f"::error title={title}::{body}")
    print(f"{n} failed test(s)")


if __name__ == "__main__":
    main(sys.argv[1])
