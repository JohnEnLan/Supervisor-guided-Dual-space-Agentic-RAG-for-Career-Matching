# v3 浜у搧杩唬鏂规锛坴2.6 路 2026-08-08 路 鍞竴鏉冨▉鍏ㄦ枃锛?
> 淇鍙诧細v1鈫抳2.5 缁忎竷杞笁鏂硅瘎瀹℃敹鏁涳紙瀛?agent 鍥?浜?鍏?涓冭疆 PASS锛汣odex
> 绗竷杞畫鐣?1B/1M/2m 浜庢湰鐗堝缃紝瑙?搂14锛夈€倂1鈥搗2.2 涓烘湭鍏ュ簱鑽夌锛沢it 鍐?> 鍓嶇増 v2.3/v2.4/v2.5銆?*姝ｆ枃鑷寘鍚?*锛涘敮涓€璺ㄦ枃妗ｆ寚閽堬細鍘嗗彶鎰忚澶勭疆琛ㄥ瓨浜?> git v2.3 搂12锛堥潪瑙勮寖鎬э級銆?> **瑙勮寖鎬у紩鐢ㄥ師鍒欙紙璇勫瑁佸畾锛寁2.6 閿氱偣淇鐗堬級**锛氫繚鐣欏瀷绾︽潫鐨勬潈濞佹簮锛?> 鐜拌浠ｇ爜涓庨拤姝诲畠浠殑娴嬭瘯锛涙湰鏂规涓嶅鍒跺瓧闈㈠€间互闃插弻婧愭紓绉伙紙渚嬪锛氬紩鑷?> 閽夋娴嬭瘯鐨勭煭瀛愪覆鍙唴鑱旓紝濡?搂3.3 瀛樻椿瀛愪覆锛夈€傚畬鎴愬垽鎹紳閿氱偣娴嬭瘯鍏ㄧ豢銆?> **閿氱偣琛紙缁忕涓冭疆閫愪竴鏍告锛?*锛?> - role_clusters **鍜ㄨ璇嶈〃**锛氭潈濞佹簮 consult_engine.py:50锛坧rompt 璇嶈〃锛?>   **涓嶅惈 other**锛夈€傚矖浣嶄晶鑱氱被璇嶈〃锛堝惈 other鈥斺€攃onsult_engine.py:818-831銆?>   scripts/load_jobs.py:145-160锛夋槸**鍙︿竴涓泦鍚?*銆佺敤閫斾笉鍚岋紝涓嶅睘鏈害鏉燂紱
>   涓よ〃骞跺瓨闈炲啿绐侊紝绯绘湁鎰忓垎灞傦紙瑁佸畾璁板綍浜庢锛夈€傜幇鏈夋祴璇曞彧鎶芥煡涓夊€硷紝
>   **B3 鏂板鍏ㄩ泦閽夋蹇収娴嬭瘯**锛堣 搂3.1锛夈€?> - clarify 鍚庣紑閿悕锛歵est_resume_clarification_engine.py:**100-101**
>   锛坅nswer_summary/clarification_action 鏂█澶勶紱鍘熷紩 94-99 鏈夊亸锛屽凡姝ｏ級銆?> - phase 鏋氫妇涓?120/80 涓婇檺锛氬畾涔夋簮 consult_engine.py:24銆?4-95 +
>   schemas.py:204-206銆?25-227銆?*241锛圕onsultStateResponse 渚х涓夊
>   鍏紑 DTO锛?*锛涚幇鏃犲叏鍊兼祴璇曪紝**B3 閽夋蹇収涓€骞惰鐩?*锛堝洓鍊兼灇涓?+
>   120/80 甯搁噺 + 涓夊 DTO 澹版槑涓€鑷存€э細ConsultTranscriptEntry/
>   ConsultResponse/ConsultStateResponse 涓庡唴閮?ConsultPhase锛夈€?> - 鍥涘紑鍏崇煩闃碉細test_consult_coach.py:944-1116锛堢涓冭疆楠岃瘉鏈夋晥锛夈€?> - G17/G18 璇箟锛歞ocs/validation/2026-08-07-global-audit-findings.md:70銆?> 瀹硶瑁佸喅锛堢敤鎴?2026-08-08锛屽凡鍏ュ簱 de88946锛夛細`asyncio.to_thread` 鍗歌浇闃诲
> 搴撹皟鐢ㄤ负"绂?threading"纭害鏉熺殑鏄庣‘鍏佽渚嬪锛圓GENTS.md 搂2.2 /
> CLAUDE_LANGGRAPH.md 搂2.2锛夛紱浠嶇鑷缓绾跨▼/绾跨▼姹?鍏变韩鍙彉鐘舵€併€?> 鍘熷垯锛氭棤鐘舵€佹湇鍔★紙Postgres 鍗曚竴鐘舵€佹簮锛夈€乥ounded loop銆佺‖杩囨护璧?SQL銆?> evidence 涓嶇紪閫犮€佸閮ㄨ皟鐢ㄨ繃 Semaphore銆佷竴娆′竴鎵硅窇閫氬啀涓嬩竴鎵广€?
## 0. 闇€姹傛槧灏勪笌鎵ц椤哄簭

| # | 闇€姹?| 鎵规 | | # | 闇€姹?| 鎵规 |
|---|---|---|---|---|---|---|
| R1 | 鍥剧墖/鎵弿璇嗗埆 | B4 | | R6 | 灏忔剰鐑儏浜鸿 | B3 |
| R2 | 瑙ｆ瀽鍙欎簨+閫愯+鑰楁椂 | B3 | | R7 | 棣栬鍏?/welcome | B1 |
| R3 | 璐ㄩ噺鎻愮ず/璇佹嵁鎶樺彔 | B1 | | R8 | 瀵硅瘽妗嗗榻?| B1 |
| R4 | 纭涓婁紶/瑙ｆ瀽+闄?娆?| B2 | | R9 | 绉婚櫎璇勪及/鐩戞帶鍏ュ彛 | B5 |
| R5 | 閫愭潯鍑虹幇+鐢ㄦ埛姘旀场 | B1+B2 | | R10 | 绠＄悊鍛橀〉 | B5 |

椤哄簭 **B2 鈫?B1 鈫?B3 鈫?B4 鈫?B5**锛堣鍐宠惤鍦板悗浜旀壒鍧囨棤鍓嶇疆闃诲锛夈€?杩佺Щ锛欱2=0009銆丅3=0010銆丅5=0011銆?
**R4 鍙ｅ緞锛堢敤鎴风煡鎮夛級**锛氶檺棰濇寜瑙ｆ瀽娆℃暟锛坄RESUME_PARSE_LIMIT=3`锛夛紱閲嶄紶涓嶈€?棰濆害锛涘閮ㄨ皟鐢ㄥ彂璧峰墠澶辫触涓嶈€楅搴︼紙搂1.2 杩旇繕锛夈€?**R1 瑁佸噺锛堢敤鎴风煡鎮夛級**锛氱函鎵弿 DOCX 涓嶅仛鍐呭祵鍥?OCR锛屽紩瀵艰浆 PDF/鍥剧墖閲嶄紶锛?瑕嗙洊 PDF锛堝師鐢?鎵弿/娣峰悎锛? 鍥剧墖 + 鏂囨湰 DOCX銆?
## 1. B2 涓婁紶纭娴?+ 瑙ｆ瀽闄愰锛堝悗绔?+ 鍓嶇锛屽悓鎵归儴缃诧級

### 1.1 鎸佷箙鍖栵紙migration 0009锛屽畬鏁?DDL锛?
```sql
CREATE TABLE resume_uploads (
  session_id  TEXT NOT NULL REFERENCES session_state(session_id) ON DELETE CASCADE,
  generation  BIGINT NOT NULL,
  filename    TEXT NOT NULL,
  suffix      TEXT NOT NULL,
  content     BYTEA,
  extracted_text TEXT,
  pages       INT NOT NULL DEFAULT 0 CHECK (pages >= 0),
  chars       INT NOT NULL DEFAULT 0 CHECK (chars >= 0),
  ocr_suggested BOOLEAN NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, generation)
);
ALTER TABLE session_state ADD COLUMN resume_parse_count INT NOT NULL DEFAULT 0
  CHECK (resume_parse_count >= 0);
```

鍚屾 schema.sql銆備笂浼犱笉钀界鐩橈紙`persist_upload`/unlink 绉婚櫎锛?test_uploads.py 鏁存枃浠堕噸鍐欙級锛?0MB 涓婇檺鍦ㄦ柊鎸佷箙鍖栧嚱鏁板唴**娴佸紡璇诲叆鍐呭瓨缂撳啿銆?瓒呴檺 413**銆?*涓婁紶鏃舵湰鍦版彁鍙?*锛歅OST 澶勭悊鍣ㄥ唴缁?`asyncio.to_thread(
extract_resume_text_bytes, ...)` 鎵ц锛堣鍐冲厑璁革紱涓庣幇琛?intake 鍚岃竟鐣岋級锛?鎹熷潖/涓嶅彲瑙ｆ瀽鏂囦欢 鈫?**422 `unreadable_file`**锛堜笉鍏ュ簱銆佷笉鍗?generation鈥斺€?鎻愬彇鍦?accept 浜嬪姟涔嬪墠鎵ц锛屽け璐ュ嵆杩斿洖锛夈€?*intake 杈撳叆濂戠害**锛?`extract_resume_text`/`intake_resume` 澧?`bytes + suffix` 閲嶈浇锛汣LI 淇濈暀
Path 閫傞厤銆?
### 1.2 鐘舵€佹満涓庡師瀛愭搷浣滐紙SQL 璇箟鍐欐锛涗笉鍋囪璇锋眰涓茶锛?
```
awaiting_resume 鈫?resume_uploaded 鈫?resume_queued 鈫?resume_ready / resume_error
```

- `accept_resume_upload`锛堝崟浜嬪姟锛岃閿佸厛琛岋級锛?  鈶?`UPDATE session_state SET resume_upload_generation =
     resume_upload_generation + 1, status='resume_uploaded',
     confirmed_resume_version=NULL, resume_confirmed_at=NULL
     WHERE session_id=$1 RETURNING resume_upload_generation`锛?  鈶?`DELETE FROM resume_uploads WHERE session_id=$1`锛涒憿 INSERT 鏂拌銆?- `begin_resume_parse(session_id, generation, max)`锛堝崟浜嬪姟锛屽崟蹇収鍒嗙被锛夛細
  鈶?`SELECT status, resume_upload_generation, resume_parse_count,
     owner_user_id FROM session_state WHERE session_id=$1 FOR UPDATE`
     锛堟棤琛屸啋404锛沷wner_user_id 渚?搂5.1 褰掑洜锛夛紱
  鈶?閿佸唴鍒嗙被锛屼紭鍏堢骇 `parse_limit 锛?resume_changed 锛?resume_processing
     锛?resume_unparsed`锛?  鈶?`UPDATE session_state SET status='resume_queued',
     resume_parse_count = resume_parse_count + 1 WHERE session_id=$1`锛?  鈶?鍚屼簨鍔?`SELECT filename, suffix, content, extracted_text, pages, chars
     FROM resume_uploads WHERE session_id=$1 AND generation=$2`鈥斺€斿瓧鑺傚叆
     鍐呭瓨浼?BackgroundTask锛堣缂哄け鈫掑洖婊氾紝鎸?resume_changed锛夈€?  宸茶瘉锛氫笌 accept 鐨勫叏閮ㄤ氦閿欏湪琛岄攣涓茶鍖栦笅瀹夊叏锛涘弻鍑诲崟鎵ｃ€?- `save_normalized_resume` / `mark_resume_error`锛?*鏀归€犱负鍗曚簨鍔?CAS +
  缁堟€佷簨浠?*锛夛細涓ゅ嚱鏁板悇澧炲彲閫?`terminal_event` 鍙傛暟锛岀被鍨?  `TerminalEvent{step: Literal["done","error"], text: str,
  elapsed_ms: int}`锛涘疄鐜颁负**鍚屼竴浜嬪姟鍐?*
  `UPDATE session_state ... WHERE session_id=$1 AND
  resume_upload_generation=$n AND status='resume_queued'
  RETURNING session_id` 鈥斺€?**RETURNING 鍛戒腑鎵?* INSERT 缁堟€佽繘搴︿簨浠?  锛堜笉甯?搂3.1 鐨?EXISTS 瀹堝崼锛屾褰撴€х敱 CAS 淇濊瘉锛夛紱鏈懡涓暣浣?no-op銆?  涓嶅啓浠讳綍浜嬩欢锛堣ˉ CAS miss 鍏ㄥ洖婊氭祴璇曪級銆?*seq 鍒嗛厤鍗忚**锛氶潪缁堟€佷簨浠?  鐢变换鍔″唴璁℃暟鍣ㄥ垎閰?1..99锛涚粓鎬佸浐瀹?`seq=100`锛堜繚鐣欐锛夆€斺€旀瘡浠ｄ粎涓€涓?  浠诲姟锛坆egin CAS 淇濊瘉锛変笖缁堟€佽嚦澶氫竴娆★紙鏈?CAS 淇濊瘉锛夛紝PK 鍐茬獊鎸夋瀯閫?  涓嶅彲杈撅紱涓囦竴鍙戠敓鍒欎簨鍔″洖婊氭暣浣?no-op銆?- **杩旇繕**锛歚_normalize_resume` 鍗?try/finally 鍐呯淮鎶?`external_started`
  锛堣繘搴﹂樁娈?normalizing/ocr 缃綅锛夛紱澶辫触涓旀湭缃綅 鈫?  `UPDATE session_state SET resume_parse_count =
  GREATEST(resume_parse_count - 1, 0) WHERE session_id=$1`锛堟棤 generation
  璋撹瘝锛涙墸璐瑰厛浜庝换鍔″惎鍔ㄥ凡鎻愪氦锛屽綊绾充繚璇佹甯歌繍琛屼笉瑙︿笅闄愶紱鍗?finally =
  姣忎换鍔♀墹1 娆¤繑杩樼殑缁撴瀯淇濊瘉锛夈€俛dmin 閲嶇疆涓庡湪閫斾换鍔′氦閿欏彲澶氳繕 1 娆?  锛堜笂鐣?1/浠诲姟锛屽亸鍚戠敤鎴凤紝宸叉帴鍙楋級銆俽estart 涓换鍔＄儳 1 娆★紝鏁戞祹 搂5.3銆?- 娓呯悊锛氫换鍔?finally `UPDATE resume_uploads SET content=NULL,
  extracted_text=NULL WHERE session_id=$1 AND generation=$2`锛堟竻鐞嗚寖鍥达紳
  涓婁紶鍘熶欢涓庝复鏃舵彁鍙栧壇鏈紱resume_state 鐨勮瘉鎹?鎽樿灞炰骇鍝佹暟鎹紝淇濈暀锛夈€?- `_RESUME_LIFECYCLE_DETAILS` 澧?`resume_unparsed`銆乣resume_parse_limit`銆?- **鐢熷懡鍛ㄦ湡鏃犳潯浠朵繚鎶わ紙涓?clarify flag 瑙ｈ€︼級**锛?  - consult/finalize 绔偣鍓嶇疆锛堟棤鏉′欢锛夛細`resume_uploaded`鈫?09 unparsed銆?    `resume_queued`鈫?09 processing锛沗resume_error` 鐣?flag 闂ㄦ帶锛堝熀绾匡級銆?  - **consult 钀藉簱淇濇姢锛坓eneration 涓轰富鍒ゆ嵁锛? 鎵€闇€濂戠害鎵╁睍锛堜笁浠讹紝
    瀹炵幇鍓嶇疆鍐欐锛?*锛?i) `mutate_state_atomically` 鍚?mutator 澧炰紶
    locked.status锛坄_load_locked_state` 宸?SELECT 璇ュ垪锛屼粎绌垮弬锛夛紱
    (ii) **mutator 杩斿洖鍗忚**锛氱敱"杩斿洖涓氬姟缁撴灉"鏀逛负杩斿洖
    `MutationOutcome{result: Any, status_override: str | None |
    KEEP_SENTINEL}`鈥斺€擿KEEP`锛堥粯璁わ級锛濇部鐢ㄨ皟鐢ㄦ柟浼犲叆鐨?persisted_status锛?    `None`锛濇湰娆′笉鍐?status 鍒楀彧钀?state锛堣鍐欒矾寰勫凡瀛樺湪锛夛紱`str`锛濊鍐欍€?    鏃㈡湁璋冪敤鐐逛互 KEEP 璇箟闆惰涓哄彉鍖栧湴杩佺Щ锛?iii) flag-off consult 璇昏矾寰?    鐢?`load_state` 鎹负甯?generation 鐨?context loader銆?    鍒ゅ畾锛氳閿佸唴 `locked.generation != loaded_generation 鈭?locked.status 鈭?    {'resume_uploaded', 'resume_queued'}`锛堝叏鍚嶏紝涓庣姸鎬佹満瀛楅潰涓€鑷达級鈫?    status_override=None 鍙拷鍔?transcript锛堥檷绾ц矾寰勮烦杩?    `_merge_feature_a_resume_state`锛夈€傚弻 flag 閰嶇疆鍚勬祴銆?  - **match-brief**锛歡eneration 姣斿鎻愬嚭 flag 闂ㄦ帶锛堟棤鏉′欢鐢熸晥锛屽け閰嶁啋409
    resume_changed锛夛紱**version 姣斿缁存寔 flag 闂ㄦ帶涓嶅彉**锛堥槻鎵撶牬
    test_api_v1.py:198 鏃㈡湁 fixture 鍩虹嚎锛涘璇ユ壒椤烘墜琛?fake 瀹炲弬浜﹀彲锛?    浜岄€変竴鍦ㄥ疄鐜版椂瀹氾紝娴嬭瘯鍙ｅ緞浠ユ涓哄噯锛夈€?
### 1.3 API 濂戠害

- `POST /sessions/{id}/resume`锛?02鈫?00锛宺equire_owned_session锛夆啋
  `ResumeUploadedResponse{generation, filename, pages, chars,
  text_preview(鈮?00瀛椔风粡 _redact_contact_text 鑴辨晱), parses_used,
  parses_limit, ocr_suggested}`锛?15 `unsupported_file_type`锛?  422 `unreadable_file`銆?- `GET /sessions/{id}/resume-upload`锛坮equire_owned_session锛夛細浠?  `status='resume_uploaded'` 杩斿洖涓婅堪鍚屾瀯鍏冩暟鎹紙涓嶅惈 content锛夛紝鍚﹀垯 404銆?- `POST /sessions/{id}/resume/parse`锛坮equire_owned_session锛?02锛夛細
  璇锋眰 DTO `ResumeParseRequest{generation: int}`鈥斺€斿繀椤诲洖浼犻瑙堟墍寰?  generation锛涙棫鏍囩椤佃В鏋愭湭棰勮鏂颁唬 鈫?409 resume_changed銆?*鍝嶅簲澶嶇敤
  鐜版湁 `ResumeAcceptedResponse{session_id, status:"resume_queued"}`**銆?- `resume-preview` / `resume-confirm` 鍦?uploaded 鎬?鈫?409 `resume_unparsed`銆?- OpenAPI 蹇収 + generated.ts + apiFixtures.ts 鍚屾壒鍐嶇敓銆?- **鏂囨。鍚屾锛圔2 鎵瑰唴瀹屾垚锛?*锛歱roject_functionality_and_code_guide.md銆?  code_guide.md銆乸roduct_guide.md 鐨勪笂浼?瑙ｆ瀽绔犺妭锛?*deploy_guide.md 鐨?  鍓嶇涓?Caddy 绔犺妭**锛堝叏鏂板畨瑁呰矾寰勬敼 releases/symlink 甯冨眬 + 棣栨
  bootstrap锛氬垱寤哄垵濮?`frontend-current` 绗﹀彿閾炬帴銆佹棫 `frontend-dist`
  鐩綍搴熷純璇存槑锛夛紝涓?搂7 閮ㄧ讲甯冨眬淇濇寔涓€鑷淬€?
### 1.4 鍓嶇锛圵orkbenchPage 涓婁紶 UX 鏁翠綋杩佺Щ锛?
- Composer 宸︿晶鍥炲舰閽堟寜閽紙`accept=".pdf,.docx,.txt"`锛涘浘鐗囧悗缂€ B4 鏀惧紑锛?  涔嬪墠缃伆鎻愮ず"鍥剧墖璇嗗埆鍗冲皢寮€鏀?锛夈€傞€夋枃浠?鈫?**鐢ㄦ埛渚ф皵娉?*锛堟枃浠跺悕+澶у皬+
  銆岀‘璁や笂浼犮€嶃€屽彇娑堛€嶏級鈫?POST upload 鈫?灏忔剰姘旀场棰勮锛堥〉鏁?瀛楁暟/鍓?600 瀛?  + `parses_used/parses_limit` + ocr_suggested 鎻愮ず锛?銆岀‘璁よВ鏋愩€嶁啋
  POST parse 鈫?鐜版湁 processing 杞銆?- 鎸傝浇鏃?GET resume-upload 鎭㈠纭鍗★紱娌跨敤浼氳瘽鍒囨崲 reset effect
  锛圵orkbenchPage.tsx L666-676锛夊苟瑕嗙洊 upload/parse 涓や釜 mutation銆?- 涓夊鏃?`<input type="file">`锛圠851/L886/Accordion锛夋敹鏁涘埌 composer锛?  `resume_error` 鏂囨鎸囧悜 composer锛?*PM 娆㈣繋璇紙L841锛変笌杈撳叆妗嗗崰浣嶇
  锛圠1112锛夊悓鎵规敼鍐欐寚鍚?composer**銆?- `resume_parse_limit` 鈫?瑙ｆ瀽鎸夐挳绂佺敤 + "鏈細璇濊В鏋愭鏁板凡鐢ㄥ畬锛?/3锛? +
  銆屾柊寤轰細璇濈户缁€岰TA + 闄勬敞"浼氳瘽棰濆害涔熺敤瀹屾椂璇疯仈绯荤鐞嗗憳閲嶇疆"銆?
### 1.5 娴嬭瘯

- 蹇呮敼鍚庣锛歵est_resume_generation_lifecycle.py锛圠233/263/425/819 鍖猴級銆?  test_api_v1.py锛坄PUBLIC_PATHS` 甯搁噺鍔?2 鏂扮鐐?+ 蹇収閲嶇敓鎴愶級銆?  test_uploads.py锛堟暣鏂囦欢锛夈€乼est_memory_phase_e.py:583銆?  test_auth_ownership.py锛圙ET resume-upload銆丳OST parse锛夈€?  test_config_env_boundary.py锛圧ESUME_PARSE_LIMIT锛夈€?- 蹇呮敼鍓嶇锛歐orkbenchPage.test.tsx锛垀L409/700/706/716/1481/1510锛?鈥?0 涓?  鐢ㄤ緥閲嶅啓锛夈€乤piFixtures.ts銆乪2e/full-flow.spec.ts銆?- 鏂板锛氬弻鍑?parse 鍗曟墸璐癸紱upload 闆?LLM锛涚 4 娆?parse 409锛涘垎绫讳紭鍏堢骇锛?  accept/begin 涓夋椂搴忎氦閿欙紱瑙ｆ瀽涓噸浼犫啋鍦ㄩ€斾骇鐗╀綔搴熶笖鏂拌瀹屽ソ锛涢噸浼犵珵鎬佷笅
  棰勫鍛煎け璐ヤ粛杩旇繕锛涘鍛煎悗澶辫触涓嶈繑杩橈紱415/422锛涘埛鏂版仮澶嶏紱鍙屾竻瀹氬悜锛?  flag=false 涓?uploaded/queued 鎬?consult/finalize 409锛沜onsult LLM 绛夊緟
  鏈?upload 鈫?钀藉簱鍙拷鍔?transcript 涓嶈鐩?status锛堝弻 flag锛夛紱match-brief
  flag-off 骞跺彂涓婁紶 鈫?409锛沺arse 鍥炰紶鏃?generation 鈫?409锛沜onfirm
  uploaded鈫抮esume_unparsed锛汫ET resume-upload 闈?uploaded鈫?04锛?  save/mark CAS miss 鏃剁粓鎬佷簨浠跺叏鍥炴粴锛涢檺棰濆悗鏂板缓浼氳瘽鍙敤銆?- 鍘熸牱鍥炲綊锛氬洓寮€鍏崇煩闃碉紙test_consult_coach.py:944 璧凤級銆?  test_resume_clarification_api/engine銆乼est_intent_consultation銆?  test_api_concurrency銆乪2e/mobile.spec.ts銆?
## 2. B1 鍓嶇浣撻獙鍖咃紙绾墠绔級

1. **R7 棣栬娴?*锛歚/` 鍦?`!hasSeenIntro()` 鏃?`<Navigate to="/welcome">`
   锛圕SR 鍚屾鍒ゆ柇锛夈€?welcome 椤堕儴銆岃烦杩囦粙缁嶃€嶄笌搴曢儴 CTA 鍧囨墽琛?   `markIntroSeen()` 鍚?*鍥炶 `hasSeenIntro()`**鈥斺€攖rue 鈫?`navigate("/")`锛?   false锛坙ocalStorage 涓嶅彲鍐欙級鈫?`navigate("/login")` 鐩磋揪锛沬ntroSeen.ts
   澧炴ā鍧楃骇鍐呭瓨鏃楁爣鍏滃簳銆傞椤点€岃繘鍏ュ簲鐢ㄣ€嶁啋 宸茬櫥褰?`/app` 鍚﹀垯 `/login`锛?   銆屼簡瑙ｅ畠濡備綍宸ヤ綔銆嶅叆鍙ｄ繚鐣欍€傛洿鏂?HomePage/WelcomePage/router 娴嬭瘯銆?2. **R5 閫愭潯鍑虹幇**锛歚useStaggeredReveal` hook鈥斺€斾粎瀵?*鏈杞鏂板**娑堟伅
   鎸夊簭 `animation-delay = i*450ms`锛堝巻鍙叉秷鎭笉閲嶆挱锛夛紱PM 涓庡皬鎰忎袱鏉℃杩庤
   鍏?PM銆?00ms 鍚庡皬鎰忥紱`prefers-reduced-motion` 鍏ㄩ儴鍗虫椂銆?3. **R3 鎶樺彔**锛歊esumeProfileAccordion 鍐呫€屾。妗堣川閲忔彁绀恒€嶃€屽師鏂囪瘉鎹€嶇Щ鑷?   鏈熬鍚勫寘 `<details>`锛坰ummary 甯︽潯鏁板窘鏍囷級锛泇itest 鏂█榛樿鏀惰捣銆?   鐐瑰嚮灞曞紑銆?4. **R8 瀵归綈锛堝彲閲忓寲锛?*锛?75/768/1280px 涓夋。妫€鏌ラ」鈥斺€攇rouped 娑堟伅宸︾缉杩?   = 澶村儚鍒楀+闂磋窛锛涙皵娉″唴鍗＄墖 padding 缁熶竴 16px锛沜omposer 琛屽唴鍏冪礌鍨傜洿
   灞呬腑锛泂tage divider 涓婁笅闂磋窛鐩哥瓑锛涚‘璁ゅ崱鎸夐挳鍙冲榻愩€傞獙鏀剁墿锛濅笁妗ｆ埅鍥俱€?
## 3. B3 灏忔剰瑙ｆ瀽鍙欎簨 + 妗ｆ閫愯 + 璁℃椂 + 浜鸿

### 3.1 杩涘害浜嬩欢锛坢igration 0010锛屽畬鏁?DDL锛?
```sql
CREATE TABLE resume_intake_progress (
  session_id  TEXT NOT NULL REFERENCES session_state(session_id) ON DELETE CASCADE,
  generation  BIGINT NOT NULL,
  seq         SMALLINT NOT NULL,
  step        TEXT NOT NULL,
  text        TEXT NOT NULL,
  elapsed_ms  INT NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, generation, seq)
);
```

- 闈炵粓鎬佷簨浠讹紙intake 鍥炶皟鍙戝嚭锛歳eceived/extracted/normalizing/ocr/
  validated锛夛細棣栦簨浠朵簨鍔?= `DELETE ... WHERE session_id=$1 AND
  generation < $2` + 瀹堝崼 INSERT锛涙瘡鏉?INSERT 甯?`WHERE EXISTS(SELECT 1
  FROM session_state WHERE session_id=$1 AND resume_upload_generation=$2
  AND status='resume_queued')`锛汦XISTS 涓哄揩鐓ц锛屾瀬绔氦閿欎笅鏃т唬鍙畫鐣?  鏃犲瀛ゅ効琛岋紙涓婄晫锛濊浠ｉ潪缁堟€佷簨浠舵暟锛屼笌 搂8 鍙ｅ緞涓€鑷达紱PK 鍚?generation銆?  璇荤鎸夊綋鍓嶄唬杩囨护锛夈€?- **缁堟€佷簨浠讹紙done/error锛?*锛氱敱 save_normalized_resume/mark_resume_error
  缁?`terminal_event` 鍙傛暟鍦?搂1.2 鐨勫崟浜嬪姟 CAS 鍐呭啓鍏ワ紙RETURNING 鍛戒腑鎵?  鍐欙級锛沬ntake 鍥炶皟**涓嶈惤**缁堟€佷簨浠讹紝浠呮壙杞戒俊鎭紙鍚?搂1.2 闃舵鏍囪淇℃伅婧愶級銆?- `intake_resume` 澧炲彲閫夊紓姝ュ洖璋?`progress`锛堥粯璁?None 琛屼负涓庣幇鐘朵竴鑷达級銆?- **`GET /sessions/{id}/resume-progress`锛坮equire_owned_session锛夊绾?*锛?  200 `ResumeProgressResponse{generation: int|null, status: str,
  events: [{seq, step, text, elapsed_ms, created_at}], done: bool}`鈥斺€?  events 鍙?`session_state.resume_upload_generation` 褰撳墠浠ｃ€乣ORDER BY seq`
  鍏ㄩ噺杩斿洖锛堝崗璁‖涓婄晫 鈮?00 琛岋紙闈炵粓鎬?seq 1..99 + 缁堟€?seq=100锛夛紝甯告€?  鈮?0锛屾棤闇€娓告爣锛夛紱浠庢湭涓婁紶锛堝垪鍊?0锛夆啋
  `generation=null, events=[]`锛?*`done = status != 'resume_queued'`**
  锛堢寮€ queued 鍗崇粓鈥斺€攔eady/error/uploaded 鍏ㄩ儴鍋滆疆璇紝瑕嗙洊"瑙ｆ瀽涓噸浼?
  浜ら敊锛氶噸浼犲悗鐘舵€佷负鏂颁唬 resume_uploaded 鈫?done=true锛屽墠绔仠杩涘害杞骞?  鍥炶惤纭鍗★級銆傚墠绔弻淇濋櫓锛氳褰曞彂璧?parse 鏃剁殑 generation锛屽搷搴?  generation 鍙樺寲鍗冲仠骞跺埛鏂颁笂浼犳€併€傝ˉ璇ヤ氦閿欐祴璇曘€?- 鍓嶇锛氫簨浠舵寜灏忔剰姘旀场閫愭潯鍑虹幇锛堝鐢?B1 stagger锛夛紱done 灞曠ず"鐢ㄦ椂 X.X 绉?銆?- 娴嬭瘯锛氬洖璋冨簭鍒楋紱DELETE 浠ｆ暟璋撹瘝浜ら敊锛堣繜鍒版棫浠诲姟鍒犱笉鎺夋柊浠ｏ級锛涚粓鎬佷簨浠?  浠呴殢 CAS 鍛戒腑鍐欏叆锛涙墍鏈夋潈锛涘墠绔?1200ms 杞娓叉煋銆乨one 鍋滆疆璇€侀€愯
  鍔ㄧ敾 + reduced-motion锛?*濂戠害閽夋蹇収娴嬭瘯锛圔3 鏂板锛岃ˉ榻愬ご閮ㄩ敋鐐硅〃
  澹版槑鐨勭己澶辨潈濞侊級**锛欳ONSULT_PROMPT 鍐?role_clusters 鍜ㄨ璇嶈〃**鍏ㄩ泦**銆?  phase 鍥涘€兼灇涓俱€?20/80 涓婇檺甯搁噺銆佷簲鏉″瓨娲诲瓙涓测€斺€斿叏閮ㄩ€愬瓧鏂█銆?
### 3.2 妗ｆ閫愯 print锛堝墠绔姩鐢伙級

- 瑙ｆ瀽瀹屾垚鍚庡皬鎰忓彂"妗ｆ鎽樿"姘旀场锛氬墠绔敱 preview 鏁版嵁鍚堟垚琛屾暟缁勶紙鏁欒偛/
  姣忔缁忓巻/姣忎釜椤圭洰/鎶€鑳藉悇涓€琛岋級锛岄€愯鏄剧幇锛垀350ms/琛岋紝reduced-motion
  鍗虫椂锛夛紱鏈鎸囧悜銆屾煡鐪嬪畬鏁存。妗堛€嶃€備笉寮曞叆 SSE銆?
### 3.3 灏忔剰浜鸿锛圧6锛?
- CONSULT_PROMPT 璇皵娈垫墿鍐欙紙鐑儏銆佺О鍛笺€佸厛鍏辨儏鍐嶆彁闂€乪moji 鈮?/鏉★級銆?- **瀛樻椿瀛愪覆閫愬瓧淇濈暀**锛氬紑澶?`PHASE_C2_CONSULT_ADVISOR\n`銆?  `Current consultation phase: {phase}`銆乣Ask exactly ONE heuristic
  question per turn`銆乣question max 80 Chinese characters`銆乣Never invent
  facts about the user`銆丣SON 閿?`assistant_reply/next_question/
  profile_updates/phase_suggestion`锛坱est_consult_engine.py:112-121 閽夋锛夈€?  clarify 鍚庣紑閿悕锛坱est_resume_clarification_engine.py:**100-101** 閽夋锛夈€?  role_clusters 鍜ㄨ璇嶈〃鍏ㄩ泦锛堢敱鏈壒鏂板鐨勫绾﹂拤姝诲揩鐓ф祴璇曢拤姝伙紝瑙?搂3.1锛夈€?  120/80 涓婇檺銆乸hase 鏋氫妇銆乥ounded retry 2 涓嶅姩銆?- 鍓嶇娆㈣繋璇?閿欒鏂囨鐑儏鍖栵紙涓嶅洖閫€ B2 鐨?composer 鎸囧悜锛夛紱杩涘害浜嬩欢妯℃澘
  鍗冲皬鎰忓彛鍚伙紙"鏀跺埌锛佹垜鍏堟妸绠€鍘嗚涓€閬嶏綖"锛夈€?
## 4. B4 瑙嗚 OCR 鍏滃簳锛堝悗绔?+ 鍓嶇 accept锛涙棤杩佺Щ锛?
- `app/llm/qwen_vl.py`锛欴ashScope OpenAI 鍏煎锛宍QWEN_VL_MODEL=qwen-vl-ocr`
  锛堥鏃ョ湡瀹炲啋鐑熺‘璁ゆā鍨嬪悕/鍙傛暟锛夛紝`Semaphore(VL_MAX_CONCURRENCY=2)`銆?- 闃诲鍗歌浇锛氬厜鏍呭寲/缂栫爜璧?`asyncio.to_thread`锛堝娉曡鍐冲厑璁镐緥澶栵級銆?- 鎻愬彇濂戠害椤电骇閲嶆瀯锛歚extract_resume_text` 鈫?`[(page_no, text)]`锛堝澶栨嫾鎺?  鍏煎锛沞vidence page 璇箟涓嶅彉锛泃est_resume_intake 鍥炲綊锛夈€?- 绛栫暐锛?  - PDF锛氶〉鏂囨湰 `< RESUME_OCR_PAGE_MIN_CHARS(50)` 鈫?璇?mediabox锛?    `scale = min(RESUME_OCR_RENDER_SCALE(2.0),
    sqrt(RESUME_OCR_MAX_PIXELS(4_000_000)/(w*h)))` 鍏夋爡鍖?鈫?JPEG q70 鈫?    base64 鈮?0MB锛熷惁鍒?q50 閲嶈瘯 鈫?浠嶈秴鍒?*璺宠繃璇ラ〉**锛堜繚鐣欏師鐢熸枃鏈紝
    涓嶇‖澶辫触锛夆啋 OCR銆?*鍚堝苟锛濇寜椤垫浛鎹?*锛岄〉搴忎笉鍙橈紱
    `RESUME_OCR_MAX_PAGES(6)` 鍙檺 OCR 椤垫暟锛屽叾鍚庨〉淇濈暀鍘熺敓鏂囨湰锛?    **鍏ㄩ儴璺抽〉/鎴柇璇存槑鍚堝苟涓哄崟鏉℃眹鎬昏繘搴︿簨浠?*锛堟帶鍒舵瘡浠ｄ簨浠惰鏁帮級銆?  - 鍥剧墖锛?*瑙ｇ爜闃茬偢=鏄惧紡灏哄妫€鏌?*鈥斺€擿Image.open` 鍚庤 header 灏哄锛?    `width*height > RESUME_OCR_MAX_IMAGE_PIXELS_DECODE(40_000_000)` 鈫?    纭嫆缁濓紙涓婁紶鎬?422 / 瑙ｆ瀽鎬?resume_error锛夛紱涓嶄緷璧?Pillow
    `MAX_IMAGE_PIXELS`锛堝叾瓒呴檺榛樿浠呭憡璀︺€佽秴涓ゅ€嶆墠鎶涢敊锛夛紱JPEG draft
    闄嶉噰鏍?鈫?褰掍竴鍖栧埌 MAX_PIXELS 鈫?鍚岀绾裤€?  - DOCX锛氫粎鏂囨湰锛涙棤鏂囨湰 鈫?resume_error + "杞?PDF 鎴栧浘鐗囬噸浼?銆?- **鍥剧墖鐨勪笂浼?瑙ｆ瀽闃舵杈圭晫锛圔4 鍐呭畾涔夛級**锛氬浘鐗囧悗缂€锛?png/.jpg/.jpeg/
  .webp锛屾寜鍚庣紑鍒ゅ畾锛夊姞鍏ョ櫧鍚嶅崟鍚庯紝**涓婁紶闃舵闆?VL 璋冪敤**鈥斺€斾粎鍋?header
  瑙ｇ爜灏哄妫€鏌ワ紙>40M 鍍忕礌 鈫?422 unreadable_file锛夛紝鍏ュ簱
  `extracted_text=''銆乸ages=1銆乧hars=0銆乷cr_suggested=true`锛?  text_preview 鍥哄畾涓?鍥剧墖绠€鍘嗭紝纭瑙ｆ瀽鍚庡皢杩涜瑙嗚璇嗗埆锛堢害鍑犲垎閽憋級"锛?  鍚堟硶鍥剧墖**涓嶄細**鍥犳棤鏂囨湰琚?422锛?22 鐨?涓嶅彲瑙ｆ瀽"浠呴€傜敤 pdf/docx 鎻愬彇
  寮傚父锛夈€俈L 鍙湪纭瑙ｆ瀽鍚庣殑浠诲姟鍐呰皟鐢ㄣ€?- 缁堟锛氬綊涓€鍖栧悗鏃犱换浣曞彲鐢?evidence span 鈫?resume_error锛圙17锛夈€?- pypdfium2銆丳illow 鍏?requirements.txt锛涘墠绔?accept 鏀惧紑鍥剧墖 +
  ocr_suggested 鏂囨锛堝墠鍚庣鎵癸紝鍥涢棬鍚?vitest + frontend-dist 鍖咃級銆?- **B4 閰嶇疆涓庢枃妗ｅ悓姝?*锛歚.env.example` 涓?`deploy/env.production.template`
  澧?搂7 鎵€鍒?8 涓?VL/OCR 鍙橀噺锛沝eploy_guide锛堜緷璧栧畨瑁咃級銆?  product_guide锛堝浘鐗囩畝鍘嗚鏄庯級銆乧ode_guide锛圤CR 绠＄嚎锛夊悓鎵规洿鏂般€?- 娴嬭瘯锛坥racle 涓庢鏂囬€愬垎鏀棴鍚堬級锛氭贩鍚?PDF 浠呬綆鏂囨湰椤?OCR + 鎸夐〉鏇挎崲锛?  **q70 鍚堟牸鈫扸L 鎭拌皟 1 娆★紙payload 涓?q70 缂栫爜锛夛紱q70 瓒呪啋q50 鍚堟牸鈫扸L 鎭?  璋?1 娆★紙payload 涓?q50 缂栫爜锛岀紪鐮佸皾璇曟伆 2 娆★級锛涘弻瓒呪啋VL 0 娆?+ 淇濈暀
  鍘熺敓鏂囨湰 + 璺抽〉浜嬩欢**锛汳AX_PAGES 鎴柇鍚庡師鐢熸枃鏈〉淇濈暀锛?  **40_000_000 鍍忕礌鎭板ソ閫氳繃銆?0_000_001 纭嫆**锛堝弻杈圭晫锛夛紱scale 鏀舵暃鍐呭瓨
  鏈夌晫锛沄L Semaphore 涓婇檺锛涘浘鐗囦笂浼犻樁娈?VL 0 娆★紱docx 鏃犳枃鏈紩瀵硷紱
  `RESUME_OCR_ENABLED=false` 閫愬瓧鑺傜瓑浠凤紱鏃?span鈫抏rror锛涘墠绔浘鐗囧叏娴佺▼銆?
## 5. B5 璁￠噺 + 绠＄悊鍛橈紙migration 0011锛屽畬鏁?DDL锛?
```sql
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id TEXT, session_id TEXT,
  provider TEXT NOT NULL, model TEXT NOT NULL, purpose TEXT NOT NULL,
  prompt_tokens INT, completion_tokens INT,
  total_tokens INT NOT NULL DEFAULT 0
);
CREATE INDEX idx_llm_usage_created ON llm_usage (created_at);
CREATE INDEX idx_llm_usage_user ON llm_usage (user_id, created_at);
CREATE TABLE product_events (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  kind TEXT NOT NULL, user_id TEXT
);
CREATE INDEX idx_product_events_kind ON product_events (kind, created_at);
```

### 5.1 璁￠噺锛堜换鍔″叆鍙?usage_scope锛岄浂绛惧悕鏀瑰姩锛?
- 涓よ〃鍧?**await 鍐欏叆 + fail-open**锛堥仴娴嬪紓甯镐笉寰楀奖鍝?P0锛涘崟娴嬭鐩栵級銆?- `app/llm/usage_context.py::usage_scope(user_id, session_id, purpose)`
  锛坈ontextvars锛夛紝**鍏ㄩ儴鍦ㄤ换鍔′綋鍐呰缃?*锛歚_normalize_resume`
  锛坥wner_user_id 鏉ヨ嚜 搂1.2 **begin_resume_parse 姝ラ鈶?* 鐨?SELECT锛?  normalize锛孫CR 娈靛祵濂?ocr锛夈€乧onsult
  绔偣锛坈onsult锛夈€乧oach锛坈oach锛夈€?*run 缁熶竴鍖呰鍣?  `_run_with_usage_scope(...)`鈥斺€旈€忎紶 executor 鏃㈡湁鍏ㄩ儴鍙傛暟涓庢敞鍏ワ紙鍚?  LangGraph checkpointer锛宺uns.py:68-74 娉ㄥ叆鍘熸牱淇濈暀锛夛紝浠呴澶栧寘 scope锛?  瑕嗙洊缁忓吀 orchestrator 涓?`run_graph_match` 涓ゆ敮**锛堝唴灞?supervisor/
  strategy/explain 宓屽缁嗗垎锛夈€乵emory/case_base锛坈ase_embed锛夈€?- 璁板綍鍦ㄥ鎴风鍐呴儴锛歞eepseek.chat銆乹wen_embed锛坋mbed_one 澶嶇敤 embed_texts
  鏃?*鍙湪鏈€鍐呭眰 provider 璇锋眰澶勫啓涓€琛?*锛汱RU 鍛戒腑闆惰锛夈€乺eranker
  锛堜粎 total锛夈€乹wen_vl銆傛墍鏈夊嚱鏁扮鍚嶄笉鍙橈紝鏃㈡湁娴嬭瘯鍋囦欢闆跺啿鍑汇€?- product_events 鍐欏叆鐐癸細login / session_created / consult_turn /
  run_started / resume_parse銆?- 娴嬭瘯锛氬弻 executor 褰掑洜甯?session_id/user_id 涓?**checkpoint 鍐欏叆鏂█浠?  鐢熸晥**锛涘祵濂?scope锛沠ail-open锛涚紦瀛橀浂琛岋紱鍗?provider 璇锋眰鍗曡銆?
### 5.2 绠＄悊鍛橀壌鏉冿紙fail-closed + 鍗虫椂鎾ゆ潈锛?
- `require_admin`锛氫换浣曢厤缃笅瑕佹眰宸茬櫥褰?+ `users.is_admin` + **姣忚姹傚疄鏃?  鏍￠獙 email 韬唤 鈭?ADMIN_EMAILS**锛堜竴娆?user_identities 绱㈠紩鏌ヨ锛涚櫧鍚嶅崟
  绉婚櫎鍗虫椂鐢熸晥锛夈€傜櫥褰曟椂鍚屾鍒?`is_admin = (email 鈭?鐧藉悕鍗?`锛堝崌闄嶆潈鑷姩锛?  phone 韬唤鎭掗潪 admin锛夈€傝В鏋愯鑼冿細閫楀彿鍒嗛殧銆乼rim銆乧asefold銆佸幓閲嶃€?  break-glass锛歋QL 鐩存敼鍒?+ 涓存椂鍔犲洖鐧藉悕鍗曘€?- monitoring锛?*鍏?flag锛堝叧闂啋404 璇箟淇濈暀锛夊啀 require_admin**锛堝紑鍚悗
  鍖垮悕 鈫?401/403锛夛紱test_monitoring_api.py 鍖垮悕 200/404 鐢ㄤ緥鎸夋柊搴忛噸鍐欍€?- 璇勪及椤碉細/admin/evaluation 璧版柊 admin 绔偣锛堣法鐢ㄦ埛锛夛紱鐢ㄦ埛鑷煡
  `/runs/{id}/explain`锛坮equire_owned_run锛変繚鐣欎笉鍔ㄣ€?
### 5.3 绠＄悊绔?API 涓庨〉闈?
- `GET /api/v1/admin/overview`锛氱敤鎴?鐧诲綍/浼氳瘽/consult/run 璁℃暟锛堜粖鏃?7鏃?
  30鏃ワ級銆佹寜鏃?token 鏇茬嚎銆佹寜妯″瀷 token 涓庝及绠楁垚鏈紙鍓嶇鍗曚环甯搁噺锛屾爣娉?  "浼扮畻路浠锋牸鐗堟湰 2026-08"锛夈€?- `GET /api/v1/admin/users?page`锛歟mail銆佹敞鍐?鏈€杩戠櫥褰曪紙last_login_at 鍥炲～
  鏈€杩戜竴娆★級銆佷細璇濇暟銆佹渶杩戠畝鍘嗘憳瑕佸垪銆?*鏈€鏂扮畝鍘嗗畾搴?*锛?  `resume_confirmed_at DESC NULLS LAST, resume_version DESC, session_id`
  鍙栭锛涘叏绌?鈫?"鏈笂浼?銆?- `GET /api/v1/admin/users/{id}/resume`锛氭渶鏂?resume_state 鍏ㄩ噺锛堜笉鑴辨晱锛?  浠?admin锛夈€?- `GET /api/v1/admin/runs/{run_id}/explain`锛坮equire_admin锛岃法鐢ㄦ埛锛屽鐢?  鐜版湁 explain DTO锛夈€?- `POST /api/v1/admin/sessions/{id}/reset-parse-count`锛坮equire_admin锛?  **鍗曚簨鍔?FOR UPDATE**锛変笁鎬佽涔夋樉寮忓寲锛氣憼 `resume_parse_count=0` 鎭掑畾
  鎵ц锛涒憽 浠呭綋 status='resume_queued'锛坮estart 閬楃暀锛夆啋 缃?resume_error +
  娓呰浼氳瘽 resume_uploads 鐨?content/extracted_text锛涒憿
  status='resume_uploaded'锛堝悎娉曞緟瑙ｆ瀽锛夊強鍏朵綑鐘舵€?鈫?浠呮竻闆惰鏁般€佷笉鍔?  涓婁紶涓庣姸鎬併€傚搷搴?`{session_id, resume_parse_count: 0, status}`銆?- **admin 鍝嶅簲 DTO锛圤penAPI 鍙敓鎴愮骇锛屽瓧娈靛悕涓庣┖鍊肩被鍨嬪啓姝伙級**锛?  `AdminOverviewResponse{users_total: int, logins_today: int,
  logins_7d: int, logins_30d: int, sessions_total: int,
  consult_turns_total: int, runs_total: int,
  tokens_by_day: [{date: str, total_tokens: int}],
  tokens_by_model: [{model: str, prompt_tokens: int|null,
  completion_tokens: int|null, total_tokens: int}]}`锛?  `AdminUsersPageResponse{items: [AdminUserRow{user_id: str,
  email: str|null, created_at: datetime, last_login_at: datetime|null,
  session_count: int, resume_name: str|null, resume_phone: str|null,
  resume_school: str|null, resume_degree: str|null}], page: int,
  page_size: int(=20), has_more: bool}`锛?  `AdminUserResumeResponse{user_id: str, session_id: str|null,
  resume_state: object|null}`锛堟棤绠€鍘?鈫?null 瀛楁锛?00 涓?404锛夛紱
  admin explain 澶嶇敤鐜版湁 explain DTO锛涗笉瀛樺湪鐨?user/session/run 鈫?404銆?- 鍓嶇 `/admin` 杞?shell锛堝叆鍙ｄ粎 `me.is_admin` 鍙锛夛細Dashboard + 鐢ㄦ埛琛?  + 绠€鍘嗚鎯呮娊灞?+ 閲嶇疆鎸夐挳锛涖€岃瘎浼帮紙绛旇京锛夈€嶃€岀洃鎺э紙绛旇京锛夈€嶅叆鍙ｇЩ鍏?  /admin锛堟棫璺緞 Navigate 閲嶅畾鍚戯級锛涚敤鎴蜂晶 sidebar 绉婚櫎涓ゅ叆鍙ｏ紙R9锛夈€?- **B5 閰嶇疆涓庢枃妗ｅ悓姝?*锛歚.env.example` 涓?`deploy/env.production.template`
  澧?ADMIN_EMAILS锛沺roduct_guide.md 璇勪及/鐩戞帶鐢ㄦ埛鍏ュ彛绔犺妭锛堢幇 :170 闄勮繎锛?  鏀逛负 admin 鍏ュ彛璇存槑锛沜ode_guide/deploy_guide 澧炵鐞嗙璺敱涓庨儴缃叉銆?
### 5.4 绠€鍘嗚仈绯讳汉缁撴瀯鍖?
- `resume_state.contact = {name, phone, email, evidence_span_ids}`
  锛坅dditive锛夈€傝惤鐐瑰叏鍒楋細app/state/schema.py ResumeState 澧炲瓧娈点€?  resume_intake.py SYSTEM_PROMPT JSON shape 澧?contact 娈点€丩LMResumePayload
  澧炲瓧娈点€?*閫愬瓧娈?extractive 楠岃瘉锛坣ame/phone/email 鍚勮嚜閫愬瓧鍛戒腑鎵€寮?  span锛屽惁鍒欒瀛楁缃┖锛涗笉鐢ㄨ韩浠介敋鐐瑰洖閫€锛?*銆乼ests/test_resume_intake.py
  鏂板鐢ㄤ緥銆傜敤鎴蜂晶 preview 缁存寔鑴辨晱锛沘dmin 绔偣鍘熸牱杩斿洖銆?
### 5.5 B3/B4/B5 娴嬭瘯娓呭崟

- B5锛歵est_monitoring_api锛堝尶鍚嶇敤渚嬫寜鏂板簭閲嶅啓锛夈€乼est_auth_sessions
  锛堢櫥褰?SQL 鏀瑰啓 鈫?fake DB 鍖归厤鏇存柊锛孡101-140/198-223锛夈€乼est_auth_api銆?  test_auth_ownership锛坅dmin 绔偣鐭╅樀 + 鍗虫椂鎾ゆ潈锛氱櫧鍚嶅崟绉婚櫎鍚庝笅涓€璇锋眰
  403锛夈€乤dmin API 鏂版祴璇曪紙reset 涓夋€佽涔夈€乤dmin explain 璺ㄧ敤鎴枫€丷9 鍙岀
  鏂█锛氱敤鎴?sidebar 鏃犱袱鍏ュ彛 / admin 鍙锛夈€乧ontact 楠岃瘉銆乽sage 鍙?  executor + checkpoint 鏂█銆?- B3/B4锛氳 搂3.1/搂4 鍚勮嚜娓呭崟銆?
## 6. 閿佸畾濂戠害鍏煎娓呭崟

1. Feature A 鑷?resume_ready 璧蜂笉鍙橈紱鍥涘紑鍏崇煩闃甸鏈熶笉鏀癸紙鏂板鐘舵€佺敱 B2
   鏃犳潯浠跺墠缃嫤鎴紝鍩虹嚎鐘舵€佽涓洪€愬瓧鑺備竴鑷达級銆?2. 409 Literal 鍙姞鍊硷紙resume_unparsed/resume_parse_limit锛? 415/422 鏂?   detail锛沗_RESUME_LIFECYCLE_DETAILS` 鍚屾澧炶ˉ锛沗resume_missing` 浠嶄粎
   API 灞傛姏銆?3. consult 濂戠害涓?搂3.3 瀛樻椿瀛愪覆涓嶅姩銆?4. G17/G18 璇箟涓嶅彉銆侴17锛?瑙ｆ瀽澶辫触 鈫?鏄庣‘瑕佹眰閲嶄紶锛屼笉澶嶆椿鏃ф。妗?
   锛堟潈濞佹簮瑙佸ご閮ㄩ敋鐐硅〃锛夛細B2 鐨勯檺棰濅笌杩旇繕**涓嶈Е纰?* resume_error 鈫?   閲嶄紶杩欐潯璺緞鏈韩锛?resume_error 鐣?flag 闂ㄦ帶"鏉℃鍏充箮 consult 鍙揪鎬с€?   涓?G17锛堥噸浼犺姹傦級鏃犳秹銆?5. `-m app.serve`銆丼emaphore銆佹棤鐘舵€佹部鐢紱in-flight 瀛楄妭涓庝换鍔″悓瀹炰緥锛?   涓嶈法瀹炰緥瀵诲潃銆?6. 姣忔壒 OpenAPI 蹇収 + generated.ts + apiFixtures 鍐嶇敓銆?7. to_thread 鎸夊娉曡鍐虫潯娆炬墽琛岋紙AGENTS.md 搂2.2锛夈€?8. consult/match-brief 钀藉簱淇濇姢鏄柊澧為槻寰★紱鍩虹嚎鐘舵€佽浆绉讳笉鍙樸€?
## 7. 閮ㄧ讲涓庤縼绉?
- 甯歌鎵癸細鍥涢棬 鈫?commit 鈫?鎵撳寘 鈫?scp 鈫?瑙ｅ寘 鈫?杩佺Щ锛?009/0010/0011 鎵癸級鈫?  restart 鈫?curl 鍋ュ悍妫€鏌ャ€?- **B2 閮ㄧ讲椤哄簭锛堝啓姝伙級**锛?  鈶?鍚庣鍏堣锛氳В鍖?app 鈫?migrate 鈫?`systemctl restart career-rag` 鈫?     curl capabilities锛涙绐楀彛锛濇棫鍓嶇脳鏂板悗绔紝宸查獙璇佹棤瀹筹紙upload 200 琚?     鏃х蹇界暐锛宲review 鏀跺埌鏈煡 409 `resume_unparsed` 鍚庡洖钀戒笂浼犲叆鍙ｏ紝
     闆?LLM 闆跺穿婧冿級锛?*鏉滅粷鍙嶅悜绐楀彛**锛堟柊鍓嶇脳鏃у悗绔細缁曡繃纭鑷姩鐑?     LLM锛夆€斺€斿墠绔繀椤诲悗浜庡悗绔紱
  鈶?鍓嶇鐗堟湰鐩綍 + 绗﹀彿閾炬帴鍒囨崲锛氳В鍖呭埌
     `/opt/career-rag/releases/frontend-<鐗堟湰>` 鈫?     `ln -sfn <鐩綍> /opt/career-rag/current.tmp && mv -Tf
     /opt/career-rag/current.tmp /opt/career-rag/frontend-current`
     锛堢粷瀵硅矾寰勩€佸悓鏂囦欢绯荤粺淇?rename(2) 鍘熷瓙锛沗-f` 浣夸腑鏂畫鐣欑殑
     current.tmp 鍙箓绛夎鐩栵紱Caddy v2 file_server 榛樿璺熼殢 symlink 骞舵寜
     璇锋眰瑙ｆ瀽锛岀炕閾惧嵆鏃剁敓鏁堬級锛汣addyfile root 鏀规寚 `frontend-current`
     锛圔2 鎵逛竴骞舵敼锛屽惈 index.html `Cache-Control: no-store`锛夛紱
  鈶?`caddy validate --config /etc/caddy/Caddyfile` 鈫?     `systemctl reload caddy`锛堜粎鍥?Caddyfile 鏈韩鍙樻洿锛夛紱
  鈶?宸叉墦寮€鐨勬棫鏍囩椤靛埛鏂板嵆鎭㈠锛堝凡鎺ュ彈娈嬬暀锛夈€?  棣栨鍒囨崲 bootstrap 涓庡叏鏂板畨瑁呭竷灞€鍐欏叆 deploy_guide.md锛埪?.3 鏂囨。鍚屾锛夈€?  B2 鏈嶅姟鍣?env 澧?`RESUME_PARSE_LIMIT=3`锛堝啓鍏ヤ袱浠?env 妯℃澘锛夈€?- B4锛歚pip install -r requirements.txt` + env锛圦WEN_VL_MODEL銆?  VL_MAX_CONCURRENCY銆丷ESUME_OCR_ENABLED銆丷ESUME_OCR_PAGE_MIN_CHARS銆?  RESUME_OCR_MAX_PAGES銆丷ESUME_OCR_MAX_PIXELS銆丷ESUME_OCR_RENDER_SCALE銆?  RESUME_OCR_MAX_IMAGE_PIXELS_DECODE锛夈€?- B5锛歟nv 澧?ADMIN_EMAILS锛涚敤鎴烽偖绠遍噸鐧昏幏鏉冦€?
## 8. 椋庨櫓涓庡洖婊?
- B1/B3/B4/B5锛氬洖婊氾紳閮ㄧ讲涓婁竴鍖咃紙0010/0011 additive锛岀暀琛ㄦ棤瀹筹級銆?- **B2 鍥炴粴璇氬疄鏉℃**锛欱2 鏀瑰彉浜嗗緟瑙ｆ瀽鏁版嵁鐨勫瓨鏀撅紙BYTEA锛変笌鐘舵€佹満锛?  **鍓嶆粴淇浼樺厛**锛涜嫢蹇呴』鍥炴粴鍒版棫鍖咃紝娴佺▼椤哄簭鍐欐锛堟秷闄?鑴氭湰鎻愪氦鍚?  鍦ㄩ€旇姹傚啀鍐欏嚭鏂扮姸鎬?鐨勫苟鍙戠獥鍙ｏ級锛?  鈶?**鍏堝仠鏈?*锛歚systemctl stop career-rag`锛堢敤 stop 鑰岄潪 kill锛岃閬?     unit 鐨?Restart=always锛涘仠鏈嶅悗鏃犱换浣曞啓鍏ユ柟锛孋addy 瀵?API 鐭殏 502
     灞炲洖婊氬満鏅彲鎺ュ彈锛夛紱
  鈶?鎵ц鐘舵€佽縼绉昏剼鏈細`sudo -u postgres psql -d career_rag
     -v ON_ERROR_STOP=1 -f /opt/career-rag/deploy/rollback_b2.sql`鈥斺€?     鑴氭湰鍐呭锛堝崟浜嬪姟锛夛細`BEGIN; UPDATE session_state SET
     status='awaiting_resume' WHERE status IN
     ('resume_uploaded','resume_queued'); DELETE FROM resume_uploads;
     COMMIT;`锛?*鍚?resume_queued**鈥斺€攔estart 鏉€姝诲湪閫斾换鍔″悗璇ョ姸鎬?     鏃犱汉璁ら锛涗袱鏂硅瘎瀹＄嫭绔嬬‘璁わ級锛?  鈶?鎹㈠洖鏃?app 鍖?+ 鏃у墠绔紙symlink 缈诲洖鏃?release锛夛紱
  鈶?`systemctl start career-rag` 鎭㈠娴侀噺銆?  0009 琛ㄤ繚鐣欐棤瀹炽€傝剼鏈殢 B2 鎵瑰叆搴?`deploy/rollback_b2.sql`銆?- OCR 鎴愭湰闂革細纭鍒?+ 瑙ｆ瀽闄愰 + VL Semaphore + 椤垫暟/鍍忕礌/瑙ｇ爜闃茬偢/
  base64 涓婇檺銆?- 杩旇繕鍋忕疆鍙悜鐢ㄦ埛锛圙REATEST + CHECK 鍙屼笅闄愶紱reset 浜ら敊涓婄晫 1/浠诲姟锛夈€?- 閬ユ祴 fail-open锛汚DMIN_EMAILS 绌?鈫?/admin 鍏?403锛屼富绾挎棤褰卞搷銆?- 杩涘害瀛ゅ効琛屾棤瀹充笖鏈夌晫锛?*姣忎釜宸插惎鍔ㄦ棫浠?鈮?鍏堕潪缁堟€佷簨浠舵暟锛堚墹99锛屽父鎬?  涓綅鏁帮級**锛屾柊浠诲姟棣栦簨浠朵簨鍔℃寜 `generation < $2` 娓呯悊鏃т唬锛涜烦椤佃鏄?  鍚堝苟涓?*鍗曟潯姹囨€讳簨浠?*锛埪?锛夛紝甯告€佹瘡浠ｆ€昏鏁?鈮?0銆?
## 9. 娴佺▼

鏂规涓夋柟鍏?PASS 鎵嶅姩浠ｇ爜锛涙瘡鎵瑰洓闂?+ 瀵逛晶鎶芥煡锛涘叏閮ㄦ壒娆″畬鎴愬悗涓夋柟瀵瑰叏閲?diff 鏌?bug锛堟纭€?濂戠害/骞跺彂/瀹夊叏/鍥炲綊锛夛紝淇鍥炲鑷充笁鏂瑰共鍑€銆?
## 10-11. 鍘嗗彶鎰忚澶勭疆

浜旇疆璇勫鍘嗗彶鎰忚锛坴1 23 鏉°€佷簩杞?22 缁勩€佷笁杞?20 缁勩€佸洓杞?20 缁勶級鐨勫缃?瀵圭収琛ㄨ v2.3锛坓it 3368613锛壜?2 鍙婃湰鏂囦欢淇鍙诧紱鍏ㄩ儴宸插苟鍏ユ湰鐗堟鏂囥€?
## 12. 绗簲杞剰瑙佸缃紙v2.4锛?
| 鏉ユ簮 | 鎰忚 | 澶勭疆 |
|---|---|---|
| Codex B1 | "鍚?v2.2"寮曠敤涓嶅彲鎭㈠銆乬it 鍘嗗彶缂哄け | 鏈増鍏ㄦ枃鑷寘鍚紝鏃犱换浣曞閮ㄥ紩鐢紱淇鍙插０鏄庡瀹烇紙v1-v2.2 涓鸿崏绋挎湭鍏ュ簱锛?|
| Codex M1 | 搂0 娌荤悊鏉℃鑷浉鐭涚浘 | 瑁佸喅宸茶惤鍦帮紙de88946锛夛紝搂0 鏀逛负瑁佸喅璁板綍锛涢『搴忎笌闂ㄦ帶鐭涚浘闅忎箣娑堥櫎 |
| Codex M2 | consult 淇濇姢鎺ュ彛涓嶅彲瀹炵幇 | 搂1.2 涓変欢濂戠害鎵╁睍鍐欐锛堢┛鍙?locked.status銆乵utator 瑕嗗啓 status銆乫lag-off 鎹?loader锛夛紙瀛?agent 浜斿 M 绾у悓婧愶級 |
| Codex M3 | mark_resume_error 鏃犳棦鏈変簨鍔★紱瀛ゅ効缁堟€佷簨浠?| 搂1.2 鏀逛负鍗曚簨鍔?UPDATE鈥ETURNING 鍛戒腑鍚?INSERT锛沵iss 鍏?no-op + 鍥炴粴娴嬭瘯 |
| Codex M4 | reset 浼氶攢姣佸悎娉曞緟瑙ｆ瀽涓婁紶 | 搂5.3 涓夋€佽涔夛細浠?queued 閬楃暀鎵嶆竻鐞嗭紝uploaded 淇濈暀 |
| Codex M5 | progress API 鏃?DTO | 搂3.1 ResumeProgressResponse 瀹屾暣濂戠害锛堝綋鍓嶄唬/鎺掑簭/绌烘€?done/鍋滆疆璇級 |
| Codex M6 | Pillow MAX_IMAGE_PIXELS 40-80M 涓嶆嫤 | 搂4 鏄惧紡灏哄涔樼Н妫€鏌?+ 40_000_001 杈圭晫娴嬭瘯 |
| Codex M7 | B4 oracle 鍒嗘敮缂哄彛 | 搂4 涓夊垎鏀柇瑷€锛坬70 杩? q50 杩?鍙岃秴璺抽〉涓嶈皟 VL锛?|
| 瀛?agent M | mutate 濂戠害涓変欢 | 搂1.2锛堜笌 Codex M2 鍚堝苟锛?|
| 瀛?agent m1 | version 姣斿闂ㄦ帶褰掑睘 | 搂1.2 match-brief 鏉℃鍐欐 |
| 瀛?agent m2 | ln -sfn 闈炲師瀛?| 搂7 ln -sn + mv -Tf锛坮ename 鐪熷師瀛愶級 |
| 瀛?agent m3 | deploy_guide 鍏ㄦ柊瀹夎鐭涚浘/bootstrap | 搂1.3 鏂囨。鍚屾鎵╁洿 + 搂7 bootstrap |
| 瀛?agent m4 | B2 杩斿伐鏁炲彛鍗婂彞 | 瑁佸喅涓?鍏佽"锛屾潯娆惧凡闂紙鏃犻渶淇濈暀鏁炲彛锛?|

## 13. 绗叚杞剰瑙佸缃紙v2.5锛?
| 鏉ユ簮 | 鎰忚 | 澶勭疆 |
|---|---|---|
| Codex B1 | 淇濈暀鍨嬬害鏉熸湭鍐呰仈 | 澶撮儴銆岃鑼冩€у紩鐢ㄥ師鍒欍€嶈瀹氾細鏉冨▉婧愶紳浠ｇ爜+閽夋娴嬭瘯锛堥槻鍙屾簮婕傜Щ锛夛紝閿氱偣宸茬粰鍏紱涓嶅鍒跺瓧闈㈠€?|
| Codex M1 | mutator 鍗忚/鐘舵€佸悕绠€鍐?| 搂1.2 MutationOutcome{result, status_override: KEEP/None/str} + 鍏ㄥ悕 |
| Codex M2 | 瑙ｆ瀽涓噸浼犺嚧杩涘害姘镐箙杞 | 搂3.1 done=status!='resume_queued' + 鍓嶇 generation 鍙樺寲鍗冲仠 + 浜ら敊娴嬭瘯 |
| Codex M3 | terminal_event 瀛楁/seq/骞傜瓑 | 搂1.2 TerminalEvent 绫诲瀷 + seq 1..99/缁堟€?100 淇濈暀娈?+ 鍐茬獊涓嶅彲杈捐璇?|
| Codex M4 | parse/admin DTO 缂哄け | 搂1.3 澶嶇敤 ResumeAcceptedResponse锛浡?.3 鍥涗釜 Admin DTO 閫愬瓧娈?+ 404/绌烘€?|
| Codex M5 | 鍥剧墖涓婁紶闃舵杈圭晫 | 搂4 涓婁紶闆?VL銆佸昂瀵告鏌ャ€佸浐瀹?preview銆?22 涓嶉€傜敤鍥剧墖 |
| Codex M6 | 鍥炴粴澹版槑涓嶆垚绔?| 搂8 B2 鍓嶆粴浼樺厛 + rollback_b2.sql 鐘舵€佽縼绉昏剼鏈?|
| Codex M7 | B4/B5 env/鏂囨。鍚屾缂哄彛 | 搂4/搂5.3 鍚屾鏉℃锛堝惈 product_guide :170 鍐茬獊澶勶級 |
| Codex m1 | current.tmp 鐩稿璺緞/娈嬬暀 | 搂7 缁濆璺緞 + ln -sfn 骞傜瓑锛堝瓙 agent nit 鍚屾簮锛?|
| Codex m2 | 40M 鎺ュ彈杈圭晫/璋冪敤娆℃暟 | 搂4 鍙岃竟鐣?+ VL 璋冪敤娆℃暟涓?payload 鏂█ |
| Codex m3 | 鏈笂浼?generation 璇箟 | 搂3.1 鍒楀€?0 鈫?null |
| 瀛?agent m6-1 | 鑷寘鍚０鏄庡瓧闈㈢煕鐩?| 澶撮儴鎺緸鏀逛负"姝ｆ枃鑷寘鍚?+ 鍞竴闈炶鑼冩€ф寚閽? |
| 瀛?agent m6-2 | 缁堟€?CAS 婕?session_id | 搂1.2 WHERE 琛ュ叏 |
| 瀛?agent m6-3 | PUBLic_PATHS 绗旇 | 搂1.5 鏀规 |
| 瀛?agent nit | reset 涓夋€佹樉寮?RESUME_PARSE_LIMIT 鍏?env | 搂5.3 鈶?鏄惧紡 + 搂7 B2 env |

## 14. 绗竷杞剰瑙佸缃紙v2.6锛?
| 鏉ユ簮 | 鎰忚 | 澶勭疆 |
|---|---|---|
| Codex B1 | 鍥涗釜閿氱偣铏氳锛堣瘝琛ㄥ弻婧愬啿绐?clarify 閿鍙峰亸/phase路120路80 鏃犳祴璇?G17 鏄犲皠閿欙級 | 澶撮儴閿氱偣琛ㄥ叏闈㈡牳姝ｏ細瑁佸畾鍜ㄨ璇嶈〃涓庡矖浣嶈仛绫昏瘝琛ㄤ负涓や釜闆嗗悎锛坈onsult_engine.py:50 涓哄挩璇晶鏉冨▉锛夛紱clarify 閿敼 :100-101锛沺hase/120/80 缁欏畾涔夋簮 + B3 濂戠害閽夋蹇収娴嬭瘯琛ラ綈缂哄け鏉冨▉锛埪?.1锛夛紱搂6.4 G17 鎺緸淇 |
| Codex M1 / 瀛?m1 | 鍥炴粴婕?resume_queued锛堜袱鏂圭嫭绔嬪悓鍙戠幇锛?| 搂8 鑴氭湰 IN 鍙屾€?+ 鍗曚簨鍔?+ ON_ERROR_STOP |
| Codex m1 / 瀛?nit1 | 瀛ゅ効琛屼笂鐣岃〃杩板け鐪?璺抽〉浜嬩欢鍙嚮绌?鈮?0 | 搂8 涓婄晫鏀?姣忔棫浠?鈮?闈炵粓鎬佹暟"锛浡? 璺抽〉鍚堝苟鍗曟潯姹囨€讳簨浠?|
| Codex m2 | Admin DTO 瀛楁鍚?绌哄€肩被鍨?| 搂5.3 閫愬瓧娈电被鍨嬩笌 nullable 鍐欐 |
| 瀛?nit2 | 寮曠敤鍘熷垯 120/80 鑷紶鍔?| 澶撮儴鍘熷垯鍔?閽夋娴嬭瘯鐭瓙涓插彲鍐呰仈"璞佸厤 |
| 瀛?nit3 | owner_user_id 鎸囦唬姝т箟 | 搂5.1 鏀?begin 姝ラ鈶? |

## 15. 绗叓杞剰瑙佸缃紙v2.7锛?
| 鏉ユ簮 | 鎰忚 | 澶勭疆 |
|---|---|---|
| Codex M1 | 鍥炴粴瀛樺湪骞跺彂鍐欏洖绐楀彛锛堣剼鏈彁浜ゅ悗鍦ㄩ€旇姹傚啀閫犳柊鐘舵€侊級 | 搂8 娴佺▼鍐欐锛歴top 鏈嶅姟 鈫?鑴氭湰 鈫?鎹㈠寘 鈫?start锛堝惈 Restart=always 瑙勯伩璇存槑锛?|
| Codex m1 | 搂3.1 鏃т笂鐣屾畫鐣?| 搂3.1 涓ゅ瀵归綈锛氬鍎夸笂鐣?璇ヤ唬闈炵粓鎬佹暟锛涘崗璁‖涓婄晫 鈮?00锛堝惈缁堟€?seq=100锛?|
| Codex m2 / 瀛?nit | 搂3.3 鏃ц鍙?94-99/479 娈嬬暀 | 搂3.3 閿氱偣鍚屾锛欽SON 閿?112-121銆乧larify 閿?100-101銆佽瘝琛ㄥ叏闆?B3 蹇収 |
| Codex m3 | phase 绗笁澶?DTO锛坰chemas.py:241锛夋湭鍒?| 澶撮儴閿氱偣琛ㄨˉ :241 + B3 蹇収瑕嗙洊涓夊 DTO 涓€鑷存€?|
| Codex nit | psql 鍛戒护缂?-f 鍙傛暟 | 搂8 鈶?瀹屾暣鍛戒护鍐欐 |
