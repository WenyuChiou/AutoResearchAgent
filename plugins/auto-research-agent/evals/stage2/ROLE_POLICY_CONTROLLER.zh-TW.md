# Stage 2：每個執行環境的權限與固定輸出範圍

## Why

已驗證的原生設定使用 named permissions。舊 controller 只接受
`workspace-write`，且把一份設定套給所有角色。設定又必須禁止 agent
讀取輸出紀錄；每次輸出換一個資料夾，就不能重用同一份已預檢設定。

## What

新增 opt-in controller spec `schema_version: 1.1.0`。每個 home／workspace
組合都有自己的 `execution_policies` 和 `execution_preflights`。
named policy `1.1.0` 用 `capture_root` 指定一個固定禁止讀取的輸出父目錄。
每次新的 capture 必須在其下建立不同子目錄。原生工具與搜尋維持可用。

舊 spec 不加版本欄位，仍沿用 controller `1.0.0`。
named policy `1.0.0` 仍要求禁止讀取那一次的確切輸出目錄。
新介面不改 P4–P6 rubric，也不把功能測試當成科學改善。

## How

1. 為每個研究、挑戰與可行性角色準備不同 home／workspace。
2. 用 `environment_key(home, workspace)` 產生 map key。
3. 將角色設定的 SHA、名稱、telemetry 路徑及 capture_root 凍結到 policy。
4. 每個環境完成實際 read／write／search／child 預檢；只有資料夾名稱
   不同，不能證明隔離。預檢與研究執行必須使用相同設定。
5. controller 啟動前驗證所有 map、設定 bytes 與匹配預檢。
6. 保存原生紀錄後，再核對 active profile、兩份 restricted filesystem
   證據、寫入範圍、禁止讀取範圍與網路狀態。
7. 權限 map 的 hash 進入 action settings；改 map 後不能重用原完成單元。

缺 active profile 或 filesystem 證據時，明確拒絕當成已验证權限。
新增 write root、遺漏 denial、互相矛盾的兩份 filesystem 證據也拒絕。
一份 preflight 不能代替另一個角色的預檢。

## Example

角色的 workspace 是 `/roles/research/workspace`，home 是
`/roles/research/profile`，capture_root 是 `/captures/research`。
設定禁止讀取整個 capture_root，兩次執行分別寫入
`/captures/research/ideation` 與 `/captures/research/followup`。
設定 bytes 不變，且两次均保留各自的原始紀錄。
`/captures/another-role` 不在這個 frozen root 下，不能作為本角色輸出。

預檢在 workspace 建立的測試檔案由 host 保存後，只清理自己建立的
測試檔案；研究 workspace 仍須符合 controller 的空白起始要求。

## 驗收範圍

這是執行接口相容性與證據綁定修復。正式 A/B 仍需要實際角色 namespace
隔離、完整 inventory、用量、校準與兩個完整預演。普通 B-only preflight
不能取代正式隔離證明；此 PR 不宣稱 `formal-ready` 或品質改善。
