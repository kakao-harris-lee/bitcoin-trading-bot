package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// Timeframe 정의
type Timeframe struct {
	Name    string
	Minutes int
	APIPath string
}

// Candle 구조체
type Candle struct {
	Market              string  `json:"market"`
	CandleDateTimeUTC   string  `json:"candle_date_time_utc"`
	CandleDateTimeKST   string  `json:"candle_date_time_kst"`
	OpeningPrice        float64 `json:"opening_price"`
	HighPrice           float64 `json:"high_price"`
	LowPrice            float64 `json:"low_price"`
	TradePrice          float64 `json:"trade_price"`
	CandleAccTradePrice float64 `json:"candle_acc_trade_price"`
	CandleAccTradeVolume float64 `json:"candle_acc_trade_volume"`
}

// Collector 구조체
type Collector struct {
	db         *sql.DB
	httpClient *http.Client
	market     string
	apiURL     string
}

var timeframes = []Timeframe{
	{Name: "minute1", Minutes: 1, APIPath: "minutes/1"},
	{Name: "minute3", Minutes: 3, APIPath: "minutes/3"},
	{Name: "minute5", Minutes: 5, APIPath: "minutes/5"},
	{Name: "minute10", Minutes: 10, APIPath: "minutes/10"},
	{Name: "minute15", Minutes: 15, APIPath: "minutes/15"},
	{Name: "minute30", Minutes: 30, APIPath: "minutes/30"},
	{Name: "minute60", Minutes: 60, APIPath: "minutes/60"},
	{Name: "minute240", Minutes: 240, APIPath: "minutes/240"},
	{Name: "day", Minutes: 1440, APIPath: "days"},
	{Name: "week", Minutes: 10080, APIPath: "weeks"},
	{Name: "month", Minutes: 43200, APIPath: "months"},
}

func NewCollector(dbPath string) (*Collector, error) {
	db, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		return nil, err
	}

	collector := &Collector{
		db:     db,
		market: "KRW-BTC",
		apiURL: "https://api.upbit.com/v1/candles",
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}

	if err := collector.initDatabase(); err != nil {
		return nil, err
	}

	return collector, nil
}

func (c *Collector) initDatabase() error {
	for _, tf := range timeframes {
		query := fmt.Sprintf(`
			CREATE TABLE IF NOT EXISTS bitcoin_%s (
				timestamp TEXT PRIMARY KEY,
				opening_price REAL NOT NULL,
				high_price REAL NOT NULL,
				low_price REAL NOT NULL,
				trade_price REAL NOT NULL,
				candle_acc_trade_volume REAL NOT NULL,
				candle_acc_trade_price REAL NOT NULL,
				is_interpolated INTEGER DEFAULT 0
			)
		`, tf.Name)

		if _, err := c.db.Exec(query); err != nil {
			return err
		}
	}

	fmt.Println("✓ 데이터베이스 초기화 완료")
	return nil
}

func (c *Collector) fetchCandles(tf Timeframe, to string) ([]Candle, error) {
	url := fmt.Sprintf("%s/%s?market=%s&count=200", c.apiURL, tf.APIPath, c.market)
	if to != "" {
		url += "&to=" + to
	}

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: %d", resp.StatusCode)
	}

	var candles []Candle
	if err := json.NewDecoder(resp.Body).Decode(&candles); err != nil {
		return nil, err
	}

	// API 요청 제한 준수 (병렬 처리로 인해 더 길게 대기)
	time.Sleep(500 * time.Millisecond)

	return candles, nil
}

func (c *Collector) saveCandles(tf Timeframe, candles []Candle) (int, error) {
	if len(candles) == 0 {
		return 0, nil
	}

	tx, err := c.db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	checkStmt, err := tx.Prepare(fmt.Sprintf(
		"SELECT COUNT(*) FROM bitcoin_%s WHERE timestamp = ?", tf.Name))
	if err != nil {
		return 0, err
	}
	defer checkStmt.Close()

	insertStmt, err := tx.Prepare(fmt.Sprintf(`
		INSERT INTO bitcoin_%s
		(timestamp, opening_price, high_price, low_price, trade_price,
		 candle_acc_trade_volume, candle_acc_trade_price, is_interpolated)
		VALUES (?, ?, ?, ?, ?, ?, ?, 0)
	`, tf.Name))
	if err != nil {
		return 0, err
	}
	defer insertStmt.Close()

	inserted := 0
	for _, candle := range candles {
		var count int
		err := checkStmt.QueryRow(candle.CandleDateTimeKST).Scan(&count)
		if err != nil {
			continue
		}

		if count == 0 {
			_, err = insertStmt.Exec(
				candle.CandleDateTimeKST,
				candle.OpeningPrice,
				candle.HighPrice,
				candle.LowPrice,
				candle.TradePrice,
				candle.CandleAccTradeVolume,
				candle.CandleAccTradePrice,
			)
			if err == nil {
				inserted++
			}
		}
	}

	if err := tx.Commit(); err != nil {
		return 0, err
	}

	return inserted, nil
}

func (c *Collector) collectTimeframe(tf Timeframe, wg *sync.WaitGroup) {
	defer wg.Done()

	fmt.Printf("\n%s\n", "============================================================")
	fmt.Printf("📊 %s 데이터 수집 시작 (goroutine)\n", tf.Name)
	fmt.Printf("%s\n", "============================================================")

	totalCount := 0
	iteration := 0
	var toTimestamp string
	var prevOldest string

	for {
		iteration++
		candles, err := c.fetchCandles(tf, toTimestamp)
		if err != nil {
			fmt.Printf("[%s] ✗ API 요청 실패: %v\n", tf.Name, err)
			break
		}

		if len(candles) == 0 {
			fmt.Printf("[%s] ⚠️  더 이상 데이터가 없습니다.\n", tf.Name)
			break
		}

		oldest := candles[len(candles)-1]
		currentOldest := oldest.CandleDateTimeKST

		// 중복 감지
		if prevOldest == currentOldest {
			fmt.Printf("[%s] ⚠️  동일한 데이터 반복 감지. 수집 중단.\n", tf.Name)
			break
		}

		// DB 저장
		saved, err := c.saveCandles(tf, candles)
		if err != nil {
			fmt.Printf("[%s] ✗ 저장 실패: %v\n", tf.Name, err)
			break
		}

		totalCount += saved
		toTimestamp = oldest.CandleDateTimeUTC // UTC 시간 사용
		prevOldest = currentOldest

		if iteration%10 == 0 { // 10번마다 진행상황 출력
			fmt.Printf("[%s] 반복 %d: %d개 수집, %d개 저장 (총 %d개)\n",
				tf.Name, iteration, len(candles), saved, totalCount)
			fmt.Printf("[%s]   최신: %s, 최고: %s\n",
				tf.Name, candles[0].CandleDateTimeKST, currentOldest)
		}

		// 저장된 데이터가 없으면 중단
		if saved == 0 {
			fmt.Printf("[%s] ⚠️  모든 데이터가 이미 존재합니다. 수집 중단.\n", tf.Name)
			break
		}

		// 2019년 이전 중단
		oldestTime, err := time.Parse("2006-01-02T15:04:05", currentOldest)
		if err == nil && oldestTime.Year() < 2019 {
			fmt.Printf("[%s] ✓ 2019년 이전 데이터 도달. 수집 완료.\n", tf.Name)
			break
		}
	}

	fmt.Printf("[%s] ✓ 총 %d개 캔들 수집 및 저장 완료\n", tf.Name, totalCount)

	// 결측값 보간
	c.interpolateMissingData(tf)
}

func (c *Collector) interpolateMissingData(tf Timeframe) {
	fmt.Printf("[%s] 🔧 결측값 보간 시작...\n", tf.Name)

	rows, err := c.db.Query(fmt.Sprintf(`
		SELECT timestamp, opening_price, high_price, low_price,
		       trade_price, candle_acc_trade_volume, candle_acc_trade_price
		FROM bitcoin_%s
		WHERE is_interpolated = 0
		ORDER BY timestamp ASC
	`, tf.Name))
	if err != nil {
		fmt.Printf("[%s] ✗ 보간 실패: %v\n", tf.Name, err)
		return
	}
	defer rows.Close()

	type Record struct {
		Timestamp string
		Values    [6]float64
	}

	var records []Record
	for rows.Next() {
		var r Record
		err := rows.Scan(&r.Timestamp,
			&r.Values[0], &r.Values[1], &r.Values[2],
			&r.Values[3], &r.Values[4], &r.Values[5])
		if err != nil {
			continue
		}
		records = append(records, r)
	}

	if len(records) < 2 {
		fmt.Printf("[%s] ✓ 데이터 부족으로 보간 불가\n", tf.Name)
		return
	}

	interpolatedCount := 0
	interval := time.Duration(tf.Minutes) * time.Minute

	for i := 0; i < len(records)-1; i++ {
		currentTime, _ := time.Parse("2006-01-02T15:04:05", records[i].Timestamp)
		nextTime, _ := time.Parse("2006-01-02T15:04:05", records[i+1].Timestamp)

		expectedNext := currentTime.Add(interval)

		if nextTime.After(expectedNext) {
			gap := int(nextTime.Sub(currentTime) / interval)
			missingCount := gap - 1

			if missingCount > 0 {
				// 선형보간
				for j := 1; j <= missingCount; j++ {
					ratio := float64(j) / float64(gap)
					interpolatedTime := currentTime.Add(interval * time.Duration(j))

					var interpolatedValues [6]float64
					for k := 0; k < 6; k++ {
						interpolatedValues[k] = records[i].Values[k] +
							(records[i+1].Values[k]-records[i].Values[k])*ratio
					}

					// DB에 삽입
					_, err := c.db.Exec(fmt.Sprintf(`
						INSERT OR REPLACE INTO bitcoin_%s
						(timestamp, opening_price, high_price, low_price, trade_price,
						 candle_acc_trade_volume, candle_acc_trade_price, is_interpolated)
						VALUES (?, ?, ?, ?, ?, ?, ?, 1)
					`, tf.Name),
						interpolatedTime.Format("2006-01-02T15:04:05"),
						interpolatedValues[0], interpolatedValues[1], interpolatedValues[2],
						interpolatedValues[3], interpolatedValues[4], interpolatedValues[5])

					if err == nil {
						interpolatedCount++
					}
				}
			}
		}
	}

	fmt.Printf("[%s] ✓ %d개 결측값 보간 완료\n", tf.Name, interpolatedCount)
}

func (c *Collector) CollectAll() {
	fmt.Println("\n" + "============================================================")
	fmt.Println("🚀 업비트 비트코인 전체 데이터 수집 시작 (병렬 처리)")
	fmt.Println("============================================================")

	var wg sync.WaitGroup

	for _, tf := range timeframes {
		wg.Add(1)
		go c.collectTimeframe(tf, &wg)
	}

	wg.Wait()

	fmt.Println("\n" + "============================================================")
	fmt.Println("✅ 모든 시간단위 데이터 수집 완료")
	fmt.Println("============================================================")

	c.PrintStatistics()
}

func (c *Collector) PrintStatistics() {
	fmt.Println("\n📈 데이터 통계:")
	fmt.Println("------------------------------------------------------------")

	for _, tf := range timeframes {
		var total, original, interpolated int
		var oldest, newest sql.NullString

		err := c.db.QueryRow(fmt.Sprintf(`
			SELECT
				COUNT(*) as total,
				SUM(CASE WHEN is_interpolated = 0 THEN 1 ELSE 0 END) as original,
				SUM(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as interpolated,
				MIN(timestamp) as oldest,
				MAX(timestamp) as newest
			FROM bitcoin_%s
		`, tf.Name)).Scan(&total, &original, &interpolated, &oldest, &newest)

		if err != nil || total == 0 {
			continue
		}

		fmt.Printf("\n%s:\n", tf.Name)
		fmt.Printf("  전체: %s개\n", formatNumber(total))
		fmt.Printf("  원본: %s개\n", formatNumber(original))
		fmt.Printf("  보간: %s개\n", formatNumber(interpolated))
		if oldest.Valid && newest.Valid {
			fmt.Printf("  기간: %s ~ %s\n", oldest.String, newest.String)
		}
	}
}

func formatNumber(n int) string {
	s := fmt.Sprintf("%d", n)
	result := ""
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			result += ","
		}
		result += string(c)
	}
	return result
}

func (c *Collector) Close() error {
	fmt.Println("\n✓ 데이터베이스 연결 종료")
	return c.db.Close()
}

func main() {
	collector, err := NewCollector("upbit_bitcoin.db")
	if err != nil {
		log.Fatal("데이터베이스 초기화 실패:", err)
	}
	defer collector.Close()

	collector.CollectAll()
}
