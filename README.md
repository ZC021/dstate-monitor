# Linux D-state 프로세스 모니터링

여러 Linux 서버에서 `D` 상태(uninterruptible sleep)에 빠진 프로세스를 주기적으로 모아 보고, 디스크 I/O, NFS, block I/O 문제를 빠르게 의심할 수 있도록 만든 모니터링 대시보드입니다.

프로세스가 `D` 상태로 오래 머무르면 단순 `kill`로 해결되지 않는 경우가 많기 때문에, 호스트별 발생 현황과 원인 후보를 한 화면에서 보는 데 초점을 맞췄습니다.

## 구현 범위

- AWX/Ansible을 이용한 read-only 프로세스 수집 플레이북 작성
- 수집 결과를 대시보드 서버로 가져오는 Python 스크립트 작성
- 정적 HTML 대시보드 렌더링
- 합성 샘플 데이터로 로컬 미리보기 가능하도록 구성
- 실제 호스트명, 내부 주소, 계정, 운영 토큰 비식별화

## 폴더별 설명

- `awx/`: D-state 프로세스 수집용 Ansible 플레이북과 데모 inventory가 들어 있습니다.
- `dashboard/`: AWX 결과 수집, 리포트 렌더링, 간단한 웹 서빙을 담당하는 Python 코드입니다.
- `dashboard/report.sample.json`: 실제 운영 데이터가 아닌 합성 샘플 리포트입니다.
- `dashboard/config.env.example`: AWX URL, token, job template id 같은 설정 예시입니다.
- `DESIGN.md`: 설계 배경과 운영 흐름을 설명하는 문서입니다.
- `README.md`: 저장소 전체 설명 문서입니다.

## 실행 방법

샘플 데이터로 정적 대시보드를 미리 볼 수 있습니다.

```bash
cd dashboard
python3 render_dashboard.py report.sample.json index.html
python3 -m http.server 8099
```

실제 AWX와 연동하려면 `dashboard/config.env.example`을 참고해 개인용 `dashboard/config.env`를 만들고, 토큰과 내부 URL은 git에 올리지 않습니다.

## 운영 흐름

1. AWX가 여러 서버에서 read-only `ps` 정보를 수집합니다.
2. 대시보드 서버가 최신 job artifact를 가져옵니다.
3. Python 렌더러가 `report.json`을 정적 `index.html`로 변환합니다.
4. nginx Basic auth 뒤에서 운영자가 대시보드를 확인합니다.

## 공개 범위

사내 모니터링 경험을 비식별화한 저장소입니다. 실제 서버명, 내부 주소, 계정, 토큰, 장애 리포트는 포함하지 않습니다.

서버 상태를 주기적으로 관찰하고 반복 확인을 줄이기 위한 수집·렌더링 흐름을 제공합니다.
