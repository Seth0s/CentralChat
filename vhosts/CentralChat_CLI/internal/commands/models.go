package commands

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func modelsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "models",
		Short: "List inference models from catalog",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			cat, err := client.GetCloudModels()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(cat, "", "  ")
			fmt.Println(string(b))
		},
	}
}
