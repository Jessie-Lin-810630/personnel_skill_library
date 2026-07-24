
---
tags: [python-installation, Apple-Mac, IDE, 翻譯器, Anaconda, pyenv, VS-code, extension, autopep8, commands]
date: 2025-09-09
type: daily-log
alias: [Python環境安裝]

---

# 筆記大綱
記載如何在Mac本機電腦安裝python與編寫python程式碼腳本所需的環境。

# 環境建置說明

1. 環境需要安裝3大要素：翻譯器、輔助工具IDE、插件extension。
2. 翻譯器:
	- 即 python 3.9, python 3.11….,etc.
	- 新版本發佈時暫時使用前一版的避免大量bug
	- WINDOWS要安裝64 bit版本的翻譯器，不然有滿多函式庫會裝不進去（e.g. TensorFlow）

3. 輔助工具 IDE (integrated development environment):
	- IDE會幫忙programmer檢查語法、提示語法、快捷鍵，常見的IDE有VS code、PyCharm
	- VS code: 最泛用，市佔率高，microsoft提供的開源、免費IDE。
	- PyCharm: Python專用
4. 插件extension
	- 安裝到IDE的插件，達到個人風格化或是特別需求。
	- 個人風格化：排版設定工具相關插件。
	- 特別需求：串接AI agent輔助程式碼編寫。
5. 不建議用Anaconda這種相當於翻譯器/輔助工具/函式庫三合一懶人包，因為你的指令有機會跟標準python指令不一樣，很多系統預設變數可能被改掉…。

# 在Mac利用Anaconda安裝python與插件 (不推薦)

1. Download Anaconda-Mac from the Anaconda's website.
2. Install and then open the Anaconda nevigator.
3. Select 放大鏡，搜尋Terminal
4. 在Terminal 輸入"Python -- version"、或是執行"python"
5. 按下enter，會顯示安裝的python版本，例如：3.13.5
6. 於官網上下載Visual studio code（簡稱VS code）這是一個程式碼文字編輯器 ^3b6e8c
7. 開啟VS code視窗中左欄的資料夾icon (如下圖)，再於左二欄點選Open Folder用來存放後面將會邊寫好的程式碼。
		![[_attachment/installing_python_image01.png]]
8. 在資料夾中新增檔案，注意副檔名一定要掛上“.py”。
9. 開始編寫程式碼，按下command + S，將檔案儲存完畢。
10. 於左欄的Extension icon(延伸模組)，搜尋“Python”，於最右側部分視窗找到install後按下將其安裝完成。
11. 同步驟10搜尋code runner
12. 同步驟10搜尋material icon theme，為不同檔案給與icon與標記，方便編寫者辨識。
13. 同步驟10搜尋“autopep8”，自動幫程式碼排版。

14. 安裝後點選齒輪，找到settings，輸入“format on save”，並將第一項勾選起來，這代表儲存時VS code會自動幫忙排版。
	**補充：有多角形標誌代表有審核過，有審核過的套件會比較安全**
		![[installing_python_image02.png]]
		![[installing_python_image03.png]]
		![[installing_python_image04.png]]
15. 右下角找到3.13.5，按下後選取指定的直譯器（interpreter）
		![[installing_python_image05.png]]
		![[installing_python_image06.png]]
16. 如此就算完成python環境建置以及啟動interpreter。
17. 最後進行細部風格設定，於VS code視窗上方選單列找到 Code -> Preferences -> Settings，然後可針對 Font、appearance、auto save三者常見的設定做更改。 ^e6449e
	- 新手設定可以參考[這篇](https://vocus.cc/article/68fc8b5ffd89780001900159)一步一步調整出自己順眼的工作區。
	- (進階補充) 這些個人化設定，會是全域的，不隨專案而有不同風格，快速查看細節可以在VS code 視窗輸入`Command + shift + P `叫出命令面板，然後在命令面板上輸入`Preferences: Open User Settings (JSON)`，按下enter即可開啟查看。如果想要針對專案有客製化風格，例如團隊協作時可能另外有內訂規則、又不想要修改自己電腦上的全域設定的話，也可以在專案根目錄建立`.vscode`資料夾來統一存放工作區的配置文件 (Configuration files for the workspace) ，全路徑名為`.vscode/settings.json`。在這份裡面加掛的設定會有最高優先級，當設定與全域設定衝突時、會以這路徑下的json檔為優先，以下是過往用過還不錯的設定。
```javasrcipt
	{"workbench.iconTheme": "material-icon-theme",
	"editor.formatOnSave": true,
	"[python]": {"editor.defaultFormatter": "ms-python.autopep8",
				},
	"terminal.integrated.inheritEnv": false,
	"breadcrumbs.enabled": false,
	"editor.mouseWheelZoom": true,
	"editor.fontSize": 16,
	"terminal.integrated.mouseWheelZoom": true,
	"workbench.colorTheme": "Visual Studio Dark",
	"python.createEnvironment.trigger": "off",
	"python.defaultInterpreterPath": "/opt/anaconda3/bin/python",
	"autopep8.args": ["--max-line-length=120"
					],
	"chatgpt.localeOverride": "zh-TW",
	"chat.viewSessions.orientation": "stacked",
	"github.copilot.enable": {"*": true,
							  "plaintext": false,
							  "markdown": false,
							  "scminput": false,
							  "sql": false
							  },
	"claudeCode.preferredLocation": "panel",
	"terminal.integrated.fontSize": 13,
	"python.testing.unittestEnabled": true,
	"python.testing.unittestArgs": ["-v",
									"-s",
									"./test",
									"-p",
									"test_*.py"
									],
	"workbench.secondarySideBar.showLabels": false,
	}
```
18. 延伸閱讀資料[[Coding Style - Python Pre-commit 與 Coding Style 自動化檢查筆記#^1872fc| Python Pre-commit 與 Ruff 做 coding review]]：==注意 `settings.json` 可能與 ruff 工具搭配的 `pyproject.toml` 配置衝突，影響 IDE 使用體驗。==

# 在Mac利用Pyenv安裝python軟體 (推薦)
1. Pyenv是專門管理python版本的工具，在開發過程中可以根據需求很方便地**安裝**與**切換** python版本。
2. pyenv需要用brew指令安裝，先打開terminal:
	```
	# 更新homebrew套件
	brew update

	# 安裝pyenv
	brew install pyenv
	```
 3. 安裝後檢查pyenv是否安裝成功。
	```
	 pyenv --version
	```
4. 使用pyenv安裝特定版本的python
	```
	pyenv install <版號>
	# 例如：pyenv install 3.14.2
	#注意install後方不用加python。
	```
5. 按下enter開始安裝、可能要等待5-15分鐘
6. 檢查是否安裝成功
	```bash
		pyenv versions

		#可能輸出為：
		# system
		# 3.12.8
		# * 3.14.2 (set by /Users/<mac使用者名稱>/.pyenv/version)
		# 星星符號*代表，現在在用哪個版本
	```

7. 檢查 pyenv 把 python 安裝在哪個路徑
```bash
	pyenv which python

	#可能輸出：
	# /Users/little_po/.pyenv/versions/3.14.2/bin/python
```

8. 查看現在正在使用哪個版本的python，也可以用以下指令檢查。只是看不到他被安裝在哪個路徑。
	```bash
	python --version
	# 輸出範例：
	# Python 3.14.2
	```
9. 檢查現在激活 (activate) 的python環境是由哪個工具管理 (pyenv? Anaconda? others?)
	```bash
	which python3

	# pyenv管理的話應該會輸出成類似以下：
	# /Users/<mac使用者名稱>/.pyenv/shims/python3 #關鍵字.pyenv

	# 如果是Anaconda管理的話，應該會輸出以下：
	# /opt/anaconda3/bin/python
	```
	**補充：若開發過程中發現套件衝突或是印象中已經安裝過的套件突然出現import error之類的錯誤，也可以用which python3檢查看看環境現在指向哪裡，以懷疑是否發生環境污染，例如：當初套件就安裝錯環境 (想安裝在)，或是當天激活錯python環境的路徑，這件事容易發生在電腦裡有用Anaconda管理的時候，因為Anaconda會把由它建立的環境插在環境變數 ($PATH) 的最前面，導致每次開啟終端機的時候，Anaconda的環境有最優先讀取權，通常這時候你會看到終端機畫面呈現以下:**
	`(base) little_po@linxiaobodeMacBook-Air ~ % which python3 <--- 行首帶著`(base)`
	`/opt/anaconda3/bin/python3` ^35a50a
10. 設定要使用哪個python版本到全域
	```bash
		pyenv global <版號>
		# 例如：
		pyenv 3.12.8
	```
11. 同[[20250909 Mac安裝Python#^3b6e8c|在Mac利用Anaconda安裝python與插件-步驟7]]~步驟14下載且安裝VS code IDE。
12. 選擇interpreter。在VS code視窗下按下command+shift+P，選擇Python: Select Interpreter。可能會出現類似下面畫面，選擇`右上角有標示pyenv的那一區`有列出來的python版本。
	![[installing_python_image07.png]]

13. 如此就算完成python環境建置以及啟動interpreter。
14. 最後進行細部風格設定，於VS code視窗上方選單列找到 Code -> Preferences -> Settings，然後可針對 Font、appearance、auto save三者常見的設定做更改。


# 延伸彙整
- [[Python安裝]]
- [[Coding Style - Python Pre-commit 與 Coding Style 自動化檢查筆記]]
- [[20260613 - 以 venv 建立 python 虛擬環境| 使用 venv 建立虛擬環境 ]]
