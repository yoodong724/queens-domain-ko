# 저장 슬롯 플레이 시간 배치 도구

게임 13480 / Steam build 26356968의 `SaveSlotWidget`을 UAssetAPI JSON으로 읽은 뒤, 플레이 시간 레이블과 숫자를 가로 행에 배치하는 제작 도구입니다. `build_layout_json.py`는 지정된 원본 JSON의 SHA-256을 확인하고 새 JSON을 생성합니다. `JsonAssetWriter.cs`는 UAssetAPI를 사용해 그 JSON을 다시 바이너리로 기록합니다.

이 소스 저장소는 게임 자산, 패치 PAK, UAssetAPI 실행 파일을 포함하지 않습니다. 원본 게임 위젯과 UAssetAPI 1.1.0, .NET 및 별도의 Unreal 패키징 도구가 필요합니다. 다른 게임 버전에 적용하지 마세요.

원본 `SaveSlotWidget.uasset`의 SHA-256은 `d5789c9b93a1cd13df23f4799fa144fab54928860baf822e095ecdd70cfa1876`, `.uexp`는 `abd0c7597ed9f4b3b5d991129c5e30e015383693f38185b7a350034eab2dfe5e`입니다. UAssetAPI JSON의 SHA-256은 `970400a6287f5c0879faeb1284ddda9b9c2f6d705356afd79da0fb3fb63c1f01`입니다. 결과를 사용하기 전에는 원본·결과 해시, 재파싱과 실제 화면 표시를 별도로 확인해야 합니다.

레이블과 숫자의 문자열·갱신 코드는 보존합니다. 행은 숫자의 오른쪽 기준을 유지하고 레이블 오른쪽에 여백을 둡니다. 공통 위젯이므로 다른 언어에도 영향을 줄 수 있으며 모든 해상도와 시간 길이에서의 표시는 확인하지 않았습니다.
