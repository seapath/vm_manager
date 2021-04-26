#!/bin/bash
set -e
pylint --exit-zero "$@" >pylint-report.txt
/opt/sonar-scanner/bin/sonar-scanner -Dsonar.analysis.mode=preview -Dsonar.report.export.path=sonar-report.json
