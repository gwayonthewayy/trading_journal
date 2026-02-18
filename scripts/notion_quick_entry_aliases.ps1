Set-StrictMode -Version Latest

function Invoke-NotionQuickEntry {
    param(
        [Parameter(Mandatory = $true)][string]$Ticker,
        [Parameter(Mandatory = $true)][ValidateSet("매수", "매도")][string]$Side,
        [Parameter(Mandatory = $true)][double]$Qty,
        [Parameter(Mandatory = $true)][double]$Price,
        [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
        [double]$Fee = 0,
        [string]$Market = "미장",
        [string]$Name = "",
        [switch]$NewPosition
    )

    $projectRoot = "D:\주식\trading_journal"
    $scriptPath = Join-Path $projectRoot "scripts\notion_quick_entry.py"
    $runtimeEnv = "D:\주식\notion_tradingjournal\.env.runtime"

    $env:TJ_RUNTIME_ENV_FILE = $runtimeEnv

    $args = @(
        $scriptPath,
        "--ticker", $Ticker.ToUpper(),
        "--side", $Side,
        "--qty", $Qty,
        "--price", $Price,
        "--date", $Date,
        "--fee", $Fee,
        "--market", $Market
    )

    if ($Name -and $Name.Trim() -ne "") {
        $args += @("--name", $Name.Trim())
    }
    if ($NewPosition) {
        $args += "--new-position"
    }

    python @args
}

function buy {
    param(
        [Parameter(Mandatory = $true)][string]$Ticker,
        [Parameter(Mandatory = $true)][double]$Qty,
        [Parameter(Mandatory = $true)][double]$Price,
        [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
        [double]$Fee = 0,
        [string]$Market = "미장",
        [string]$Name = "",
        [switch]$NewPosition
    )
    Invoke-NotionQuickEntry -Ticker $Ticker -Side "매수" -Qty $Qty -Price $Price -Date $Date -Fee $Fee -Market $Market -Name $Name -NewPosition:$NewPosition
}

function sell {
    param(
        [Parameter(Mandatory = $true)][string]$Ticker,
        [Parameter(Mandatory = $true)][double]$Qty,
        [Parameter(Mandatory = $true)][double]$Price,
        [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
        [double]$Fee = 0,
        [string]$Market = "미장",
        [string]$Name = "",
        [switch]$NewPosition
    )
    Invoke-NotionQuickEntry -Ticker $Ticker -Side "매도" -Qty $Qty -Price $Price -Date $Date -Fee $Fee -Market $Market -Name $Name -NewPosition:$NewPosition
}

function tjbuy {
    param(
        [Parameter(Mandatory = $true)][string]$Ticker,
        [Parameter(Mandatory = $true)][double]$Qty,
        [Parameter(Mandatory = $true)][double]$Price,
        [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
        [double]$Fee = 0,
        [string]$Market = "미장",
        [string]$Name = "",
        [switch]$NewPosition
    )
    buy -Ticker $Ticker -Qty $Qty -Price $Price -Date $Date -Fee $Fee -Market $Market -Name $Name -NewPosition:$NewPosition
}

function tjsell {
    param(
        [Parameter(Mandatory = $true)][string]$Ticker,
        [Parameter(Mandatory = $true)][double]$Qty,
        [Parameter(Mandatory = $true)][double]$Price,
        [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
        [double]$Fee = 0,
        [string]$Market = "미장",
        [string]$Name = "",
        [switch]$NewPosition
    )
    sell -Ticker $Ticker -Qty $Qty -Price $Price -Date $Date -Fee $Fee -Market $Market -Name $Name -NewPosition:$NewPosition
}
